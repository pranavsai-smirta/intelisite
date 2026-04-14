"""Time and date utilities"""
from datetime import date
from dateutil.relativedelta import relativedelta

def previous_month_yyyymm(today: date = None) -> str:
    """Get previous month in YYYY-MM format"""
    d = today or date.today()
    prev = d.replace(day=1) - relativedelta(months=1)
    return prev.strftime("%Y-%m")

def format_month_display(yyyymm: str) -> str:
    """Convert YYYY-MM to 'Month YYYY' format"""
    from datetime import datetime
    try:
        dt = datetime.strptime(yyyymm, "%Y-%m")
        return dt.strftime("%B %Y")  # e.g., "January 2026"
    except:
        return yyyymm

def parse_month_from_title(month_text: str) -> str:
    """Parse 'January 2026' to '2026-01'"""
    from datetime import datetime
    try:
        dt = datetime.strptime(month_text, "%B %Y")
        return dt.strftime("%Y-%m")
    except:
        return None
