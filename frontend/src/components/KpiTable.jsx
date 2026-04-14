function CellValue({ value, unit, vsCompany, isOutlier, delta, higherIsBetter }) {
  const bgColor =
    vsCompany === 'above'
      ? 'bg-teal-50 text-teal-800'
      : vsCompany === 'below'
      ? 'bg-red-50 text-red-800'
      : 'bg-white text-slate-900'

  const deltaSign = delta !== null && delta !== undefined
    ? delta > 0
      ? '\u2191'
      : delta < 0
      ? '\u2193'
      : null
    : null

  const deltaColor =
    higherIsBetter === null || delta === null || delta === undefined
      ? 'text-slate-400'
      : (higherIsBetter && delta > 0) || (!higherIsBetter && delta < 0)
      ? 'text-teal-600'
      : 'text-red-600'

  return (
    <td className={`px-3 py-2 text-sm text-right whitespace-nowrap ${bgColor}`}>
      <div className="flex items-center justify-end gap-1">
        {isOutlier && (
          <span className="text-xs bg-amber-100 text-amber-700 px-1 rounded font-medium">!</span>
        )}
        <span>
          {value !== null && value !== undefined ? `${value}${unit ? '\u00a0' + unit : ''}` : '\u2014'}
        </span>
        {deltaSign && (
          <span className={`text-xs ${deltaColor}`}>
            {deltaSign}{Math.abs(delta).toFixed(1)}
          </span>
        )}
      </div>
    </td>
  )
}

const IOPTIMIZE_COLS = [
  { key: 'scheduler_compliance_avg', label: 'Scheduler\u00a0Compliance', unit: '%', higherIsBetter: true, deltaKey: 'scheduler_compliance' },
  { key: 'avg_delay_avg', label: 'Avg\u00a0Delay', unit: 'min', higherIsBetter: false, deltaKey: 'avg_delay_mins' },
  { key: 'chair_utilization_avg', label: 'Chair\u00a0Utilization', unit: '%', higherIsBetter: true, deltaKey: 'avg_chair_utilization' },
  { key: 'tx_past_close_avg', label: 'Tx\u00a0Past\u00a0Close', unit: '/day', higherIsBetter: false, deltaKey: 'avg_treatments_per_day' },
  { key: 'tx_mins_past_close_avg', label: 'Tx\u00a0Mins\u00a0Past\u00a0Close', unit: 'min', higherIsBetter: false, deltaKey: 'avg_treatment_mins_per_patient' },
]

const IASSIGN_COLS = [
  { key: 'iassign_utilization_avg', label: 'iAssign\u00a0Utilization', unit: '%', higherIsBetter: true, deltaKey: 'iassign_utilization' },
  { key: 'patients_per_nurse_avg', label: 'Pts/Nurse', unit: '/day', higherIsBetter: null, deltaKey: 'avg_patients_per_nurse' },
  { key: 'chairs_per_nurse_avg', label: 'Chairs/Nurse', unit: '', higherIsBetter: null, deltaKey: 'avg_chairs_per_nurse' },
  { key: 'nurse_utilization_avg', label: 'Nurse\u00a0Utilization', unit: '%', higherIsBetter: true, deltaKey: 'avg_nurse_to_patient_chair_time' },
]

const AVG_LOCATION_NAMES = ['company avg', 'copany avg', 'global avg']

function Table({ rows, cols, title }) {
  if (!rows || rows.length === 0) return null

  const avgRows = rows.filter(r => AVG_LOCATION_NAMES.includes(r.location?.toLowerCase()))
  const clinicRows = rows
    .filter(r => !AVG_LOCATION_NAMES.includes(r.location?.toLowerCase()))
    .sort((a, b) => (a.location ?? '').localeCompare(b.location ?? ''))
  const sortedRows = [...clinicRows, ...avgRows]

  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Location</th>
              {cols.map(col => (
                <th key={col.key} className="px-3 py-2 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sortedRows.map(row => {
              const isAvg = AVG_LOCATION_NAMES.includes(row.location?.toLowerCase())
              return (
                <tr
                  key={row.location}
                  className={isAvg
                    ? 'bg-slate-100 border-t-2 border-slate-300'
                    : 'hover:bg-slate-50 transition-colors'
                  }
                >
                  <td className={`px-3 py-2 whitespace-nowrap ${isAvg ? 'font-semibold text-slate-700' : 'font-medium text-slate-900'}`}>
                    {row.location}
                  </td>
                  {cols.map(col => (
                    <CellValue
                      key={col.key}
                      value={row[col.key]}
                      unit={col.unit}
                      vsCompany={row.vs_company?.[col.deltaKey]}
                      isOutlier={row.outlier_flags?.includes(col.deltaKey)}
                      delta={row.mom_deltas?.[col.deltaKey] ?? null}
                      higherIsBetter={col.higherIsBetter}
                    />
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function KpiTable({ ioptimize, iassign }) {
  return (
    <div>
      <Table rows={ioptimize} cols={IOPTIMIZE_COLS} title="iOptimize" />
      <Table rows={iassign} cols={IASSIGN_COLS} title="iAssign" />
    </div>
  )
}
