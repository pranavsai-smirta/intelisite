"""
ML Engine — Step 3.5 of the CHR pipeline.

Three analytical models, all persisted to chr_ml_analytics:

  Model 1  Isolation Forest (IF)
           Detects multi-dimensional anomalies in the KPI feature vector.
           Runs twice:
             - per-client  : flags locations that are outliers *within* their
                             own client group (intra-client context).
             - network-wide: flags locations that are outliers across the full
                             14-client network (absolute context).
           Features are Z-score normalised before fitting so no single KPI
           dominates by scale.

  Model 2  ARIMA(1,1,0)
           Forecasts next month's KPI value per location per KPI.
           Returns point estimate + 95% confidence interval.
           Falls back to a 3-month moving average (with simple CI) when:
             - fewer than MIN_ARIMA_MONTHS data points exist, OR
             - statsmodels fails to converge (warning captured, best guess returned).

  Model 3  Lag cross-correlation
           Tests: does scheduler_compliance at month T-1 predict
                  chair_utilization at month T?
           Pairs matched by location name (exact). Pearson r computed over
           all (T-1, T) pairs collected across all locations for the client.
           Stored once per location row (repeated, redundant, but makes chatbot
           queries trivially simple: no GROUP BY needed).

Design constraints:
  - Never raises — every model wraps its work in try/except and falls back to
    None values so a single bad client/KPI does not crash the pipeline.
  - Short history is not an error: TNO with 2 months will use the MA fallback
    for ARIMA and produce lag_sc_to_chair_n < MIN_LAG_MONTHS (stored but
    marked as low-confidence by the low n).
  - contamination=IF_CONTAMINATION is applied independently within each IF
    scope (per-client, network). The network IF therefore always flags exactly
    IF_CONTAMINATION * total_locations rows as anomalies.
"""

import logging
import statistics
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Isolation Forest
IF_N_ESTIMATORS   = 100
IF_CONTAMINATION  = 0.05   # 5% of locations flagged as anomalies per scope
IF_RANDOM_STATE   = 42
IF_MIN_LOCATIONS  = 2      # skip per-client IF when fewer locations exist

# ARIMA
ARIMA_ORDER       = (1, 1, 0)
ARIMA_MIN_MONTHS  = 3      # below this → moving average fallback
ARIMA_CI_ALPHA    = 0.05   # 95% confidence interval

# Lag correlation
LAG_MIN_PAIRS     = 4      # minimum (T-1, T) pairs to report r (otherwise null)

# KPIs to include in the IF feature vector (must be columns of ChrKpiWide)
IF_FEATURES = [
    "scheduler_compliance",
    "delay_avg",
    "treatments_avg",
    "tx_mins_avg",
    "chair_util_avg",
]

# KPIs to forecast with ARIMA (same list — all iOptimize numeric KPIs)
ARIMA_KPIS = {
    "scheduler_compliance":  "scheduler_compliance",
    "avg_delay_mins":        "delay_avg",
    "avg_treatments_per_day": "treatments_avg",
    "avg_treatment_mins_per_patient": "tx_mins_avg",
    "avg_chair_utilization": "chair_util_avg",
}


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def run_ml_analytics(session: Session, run_month: str, run_id: str) -> int:
    """
    Compute all three ML models for run_month and persist to chr_ml_analytics.
    Returns the total number of rows written.
    """
    from app.db.models import ChrKpiWide, RowType, KpiSource

    clinic_rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.run_month == run_month,
            ChrKpiWide.row_type  == RowType.CLINIC,
            ChrKpiWide.source    == KpiSource.IOPTIMIZE,
        )
        .order_by(ChrKpiWide.client_name, ChrKpiWide.location_name)
        .all()
    )

    if not clinic_rows:
        log.warning("ML engine: no CLINIC iOptimize rows found for %s", run_month)
        return 0

    # ── Build lookup structures ───────────────────────────────────────
    # client_locs[client][location] = {wide_col: value, ...}
    client_locs: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for row in clinic_rows:
        kv = _extract_if_features(row)
        client_locs.setdefault(row.client_name, {})[row.location_name] = kv

    # Flat map used for network-wide IF: (client, location) → feature dict
    network_locs: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {
        (row.client_name, row.location_name): _extract_if_features(row)
        for row in clinic_rows
    }

    # ── Model 1a: per-client Isolation Forest ────────────────────────
    client_if_scores: Dict[Tuple[str, str], Dict] = {}
    for client, locs in client_locs.items():
        if len(locs) < IF_MIN_LOCATIONS:
            for loc in locs:
                client_if_scores[(client, loc)] = {
                    "is_anomaly": None,
                    "score":      None,
                    "note":       "too_few_locations",
                }
            continue
        scores = _run_isolation_forest(locs)
        for loc, result in scores.items():
            client_if_scores[(client, loc)] = result

    # ── Model 1b: network-wide Isolation Forest ───────────────────────
    # Rebuild as {composite_key_str: feature_dict} for the IF helper
    net_key_locs = {f"{c}||{l}": v for (c, l), v in network_locs.items()}
    net_raw = _run_isolation_forest(net_key_locs)
    network_if_scores: Dict[Tuple[str, str], Dict] = {}
    for composite_key, result in net_raw.items():
        c, l = composite_key.split("||", 1)
        network_if_scores[(c, l)] = result

    # ── Model 3: lag cross-correlations ──────────────────────────────
    lag_results: Dict[str, Dict] = _run_lag_correlations(session, run_month)

    # ── Model 2: ARIMA per location per KPI ──────────────────────────
    arima_results: Dict[Tuple[str, str], Dict[str, Dict]] = (
        _run_arima_for_all_locations(session, run_month, client_locs)
    )

    # ── Persist everything ────────────────────────────────────────────
    total = 0

    for (client, loc) in network_locs:
        loc_key = (client, loc)

        # Row type 1: '_anomaly' — IF scores + lag correlation
        c_if  = client_if_scores.get(loc_key, {})
        n_if  = network_if_scores.get(loc_key, {})
        lag   = lag_results.get(client, {})

        _upsert_ml_row(
            session,
            run_month     = run_month,
            client_name   = client,
            location_name = loc,
            kpi_name      = "_anomaly",
            is_anomaly_client    = c_if.get("is_anomaly"),
            anomaly_score_client = c_if.get("score"),
            is_anomaly_network   = n_if.get("is_anomaly"),
            anomaly_score_network = n_if.get("score"),
            lag_sc_to_chair_r    = lag.get("sc_to_chair_r"),
            lag_sc_to_chair_n    = lag.get("sc_to_chair_n"),
            run_id               = run_id,
        )
        total += 1

        # Row type 2: one per ARIMA KPI
        for kpi_name, forecast in arima_results.get(loc_key, {}).items():
            _upsert_ml_row(
                session,
                run_month     = run_month,
                client_name   = client,
                location_name = loc,
                kpi_name      = kpi_name,
                arima_forecast  = forecast.get("forecast"),
                arima_lower_95  = forecast.get("lower"),
                arima_upper_95  = forecast.get("upper"),
                arima_n_months  = forecast.get("n_months"),
                arima_method    = forecast.get("method"),
                arima_converged = forecast.get("converged"),
                run_id          = run_id,
            )
            total += 1

    session.commit()
    log.info("ML engine: wrote %d rows for %s", total, run_month)
    return total


# ─────────────────────────────────────────────────────────────
# MODEL 1: ISOLATION FOREST
# ─────────────────────────────────────────────────────────────

def _extract_if_features(row) -> Dict[str, Optional[float]]:
    return {
        "scheduler_compliance": row.scheduler_compliance,
        "delay_avg":            row.delay_avg,
        "treatments_avg":       row.treatments_avg,
        "tx_mins_avg":          row.tx_mins_avg,
        "chair_util_avg":       row.chair_util_avg,
    }


def _run_isolation_forest(
    locs: Dict[str, Dict[str, Optional[float]]]
) -> Dict[str, Dict]:
    """
    Fit Isolation Forest on a set of locations.
    `locs` maps location_key → feature_dict.
    Returns {location_key: {"is_anomaly": bool, "score": float}}.

    Steps:
      1. Build raw feature matrix (N × 5), fill missing with column mean.
      2. Z-score normalise each column (std=0 columns left at 0).
      3. Fit IF and extract decision_function scores + predict labels.
    """
    loc_keys  = list(locs.keys())
    feat_names = IF_FEATURES
    n          = len(loc_keys)

    if n < IF_MIN_LOCATIONS:
        return {k: {"is_anomaly": None, "score": None} for k in loc_keys}

    # Build raw matrix
    raw = np.full((n, len(feat_names)), np.nan)
    for i, key in enumerate(loc_keys):
        for j, feat in enumerate(feat_names):
            v = locs[key].get(feat)
            if v is not None:
                raw[i, j] = v

    # Impute column means
    col_means = np.nanmean(raw, axis=0)
    for j in range(raw.shape[1]):
        mask = np.isnan(raw[:, j])
        raw[mask, j] = col_means[j] if not np.isnan(col_means[j]) else 0.0

    # Z-score normalise
    col_std  = np.std(raw, axis=0)
    col_std[col_std == 0] = 1.0
    col_mean = np.mean(raw, axis=0)
    X        = (raw - col_mean) / col_std

    # IF: contamination must be < 1.0 and result in at least 1 flagged row
    contamination = IF_CONTAMINATION
    if n < int(1 / contamination):
        # Too few samples to honour the contamination fraction — use "auto"
        contamination = "auto"

    try:
        clf    = IsolationForest(
            n_estimators  = IF_N_ESTIMATORS,
            contamination = contamination,
            random_state  = IF_RANDOM_STATE,
            n_jobs        = -1,
        )
        labels = clf.fit_predict(X)   # +1 = inlier, -1 = anomaly
        scores = clf.decision_function(X)  # higher = more normal
    except Exception as exc:
        log.warning("Isolation Forest failed: %s", exc)
        return {k: {"is_anomaly": None, "score": None} for k in loc_keys}

    result = {}
    for i, key in enumerate(loc_keys):
        result[key] = {
            "is_anomaly": bool(labels[i] == -1),
            "score":      round(float(scores[i]), 6),
        }
    return result


# ─────────────────────────────────────────────────────────────
# MODEL 2: ARIMA FORECASTS
# ─────────────────────────────────────────────────────────────

def _run_arima_for_all_locations(
    session: Session,
    run_month: str,
    client_locs: Dict[str, Dict[str, Dict]],
) -> Dict[Tuple[str, str], Dict[str, Dict]]:
    """
    For every (client, location), fetch the time series for each ARIMA KPI
    and produce a forecast dict.

    Returns:
      {(client, location): {kpi_logical_name: forecast_dict}}
    """
    from app.db.models import ChrKpiWide, RowType, KpiSource

    results: Dict[Tuple[str, str], Dict[str, Dict]] = {}

    for client, locs in client_locs.items():
        for location in locs:
            loc_key = (client, location)
            results[loc_key] = {}

            for kpi_logical, wide_col in ARIMA_KPIS.items():
                # Fetch all historical values for this location/KPI up to run_month
                history_rows = (
                    session.query(ChrKpiWide)
                    .filter(
                        ChrKpiWide.client_name   == client,
                        ChrKpiWide.location_name == location,
                        ChrKpiWide.source        == KpiSource.IOPTIMIZE,
                        ChrKpiWide.row_type      == RowType.CLINIC,
                        ChrKpiWide.run_month     <= run_month,
                    )
                    .order_by(ChrKpiWide.run_month.asc())
                    .all()
                )

                values = [
                    getattr(r, wide_col)
                    for r in history_rows
                    if getattr(r, wide_col) is not None
                ]

                results[loc_key][kpi_logical] = _arima_forecast(values)

    return results


def _arima_forecast(values: List[float]) -> Dict:
    """
    Fit ARIMA(1,1,0) on `values` and return the next-period forecast.

    Returns a dict with keys:
      forecast, lower, upper, n_months, method, converged

    Fallback chain:
      1. ARIMA(1,1,0) via statsmodels (preferred when n >= ARIMA_MIN_MONTHS)
      2. 3-month moving average with simple ±1.96σ CI (always succeeds)
    """
    n = len(values)

    fallback = _moving_avg_forecast(values)
    fallback["method"]    = "moving_avg"
    fallback["converged"] = False
    fallback["n_months"]  = n

    if n < ARIMA_MIN_MONTHS:
        return fallback

    try:
        from statsmodels.tsa.arima.model import ARIMA as StatsARIMA

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = StatsARIMA(values, order=ARIMA_ORDER)
            fit   = model.fit()

        fc_obj   = fit.get_forecast(steps=1)
        fc_mean  = float(fc_obj.predicted_mean.iloc[0])
        ci       = fc_obj.conf_int(alpha=ARIMA_CI_ALPHA)
        fc_lower = float(ci.iloc[0, 0])
        fc_upper = float(ci.iloc[0, 1])

        return {
            "forecast":  round(fc_mean,  4),
            "lower":     round(fc_lower, 4),
            "upper":     round(fc_upper, 4),
            "n_months":  n,
            "method":    "arima",
            "converged": True,
        }

    except Exception as exc:
        log.debug(
            "ARIMA failed for series of length %d: %s — using MA fallback", n, exc
        )
        return fallback


def _moving_avg_forecast(values: List[float]) -> Dict:
    """3-month moving average with a simple ±1.96σ confidence interval."""
    window = values[-3:] if len(values) >= 3 else values
    if not window:
        return {"forecast": None, "lower": None, "upper": None}

    ma = sum(window) / len(window)

    if len(window) >= 2:
        std    = statistics.stdev(window)
        margin = 1.96 * std
        return {
            "forecast": round(ma, 4),
            "lower":    round(ma - margin, 4),
            "upper":    round(ma + margin, 4),
        }

    return {"forecast": round(ma, 4), "lower": None, "upper": None}


# ─────────────────────────────────────────────────────────────
# MODEL 3: LAG CROSS-CORRELATION
# ─────────────────────────────────────────────────────────────

def _run_lag_correlations(
    session: Session, run_month: str
) -> Dict[str, Dict]:
    """
    For each client, compute Pearson r between:
      - scheduler_compliance at month T-1   (predictor)
      - chair_util_avg       at month T     (outcome)

    Uses all history up to and including run_month.
    Location names must match exactly for a pair to be counted.

    Returns:
      {client_name: {"sc_to_chair_r": float|None, "sc_to_chair_n": int}}
    """
    from app.db.models import ChrKpiWide, RowType, KpiSource

    results: Dict[str, Dict] = {}

    clients = [
        r[0] for r in session.query(ChrKpiWide.client_name)
        .filter(
            ChrKpiWide.source   == KpiSource.IOPTIMIZE,
            ChrKpiWide.row_type == RowType.CLINIC,
            ChrKpiWide.run_month <= run_month,
        )
        .distinct()
        .all()
    ]

    for client in clients:
        history = (
            session.query(ChrKpiWide)
            .filter(
                ChrKpiWide.client_name  == client,
                ChrKpiWide.source       == KpiSource.IOPTIMIZE,
                ChrKpiWide.row_type     == RowType.CLINIC,
                ChrKpiWide.run_month    <= run_month,
            )
            .order_by(ChrKpiWide.run_month.asc())
            .all()
        )

        # Build {month: {location: (sc, chair)}}
        by_month: Dict[str, Dict[str, Tuple[float, float]]] = {}
        for row in history:
            if (row.scheduler_compliance is not None
                    and row.chair_util_avg is not None):
                by_month.setdefault(row.run_month, {})[row.location_name] = (
                    row.scheduler_compliance,
                    row.chair_util_avg,
                )

        months_sorted = sorted(by_month.keys())
        predictor, outcome = [], []

        for i in range(1, len(months_sorted)):
            prev_m = months_sorted[i - 1]
            curr_m = months_sorted[i]
            for loc, (sc_prev, _) in by_month[prev_m].items():
                if loc in by_month[curr_m]:
                    _, chair_curr = by_month[curr_m][loc]
                    predictor.append(sc_prev)
                    outcome.append(chair_curr)

        n_pairs = len(predictor)
        r_val   = _pearson_r(predictor, outcome) if n_pairs >= LAG_MIN_PAIRS else None

        results[client] = {
            "sc_to_chair_r": r_val,
            "sc_to_chair_n": n_pairs,
        }

    return results


def _pearson_r(x: List[float], y: List[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if degenerate."""
    n = len(x)
    if n < 3:
        return None
    try:
        xm = statistics.mean(x)
        ym = statistics.mean(y)
        num  = sum((xi - xm) * (yi - ym) for xi, yi in zip(x, y))
        denx = sum((xi - xm) ** 2 for xi in x) ** 0.5
        deny = sum((yi - ym) ** 2 for yi in y) ** 0.5
        if denx == 0 or deny == 0:
            return None
        return round(num / (denx * deny), 4)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# DB UPSERT HELPER
# ─────────────────────────────────────────────────────────────

def _upsert_ml_row(
    session: Session,
    run_month: str,
    client_name: str,
    location_name: str,
    kpi_name: str,
    *,
    is_anomaly_client: Optional[bool]    = None,
    anomaly_score_client: Optional[float] = None,
    is_anomaly_network: Optional[bool]   = None,
    anomaly_score_network: Optional[float] = None,
    arima_forecast: Optional[float]      = None,
    arima_lower_95: Optional[float]      = None,
    arima_upper_95: Optional[float]      = None,
    arima_n_months: Optional[int]        = None,
    arima_method: Optional[str]          = None,
    arima_converged: Optional[bool]      = None,
    lag_sc_to_chair_r: Optional[float]   = None,
    lag_sc_to_chair_n: Optional[int]     = None,
    run_id: str                          = "",
) -> None:
    from app.db.models import ChrMLAnalytics

    existing = session.query(ChrMLAnalytics).filter_by(
        run_month     = run_month,
        client_name   = client_name,
        location_name = location_name,
        kpi_name      = kpi_name,
    ).first()

    fields = dict(
        is_anomaly_client    = is_anomaly_client,
        anomaly_score_client = anomaly_score_client,
        is_anomaly_network   = is_anomaly_network,
        anomaly_score_network = anomaly_score_network,
        arima_forecast       = arima_forecast,
        arima_lower_95       = arima_lower_95,
        arima_upper_95       = arima_upper_95,
        arima_n_months       = arima_n_months,
        arima_method         = arima_method,
        arima_converged      = arima_converged,
        lag_sc_to_chair_r    = lag_sc_to_chair_r,
        lag_sc_to_chair_n    = lag_sc_to_chair_n,
        run_id               = run_id,
    )

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        session.add(ChrMLAnalytics(
            run_month     = run_month,
            client_name   = client_name,
            location_name = location_name,
            kpi_name      = kpi_name,
            **fields,
        ))
