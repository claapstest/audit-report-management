import calendar
from datetime import datetime
import re

# Matches the common date formats in typed audit reports:
#   12/05/2026, 12-05-2026, 5 May 2026, May 5, 2026, May 5 2026
DEFAULT_DATE_REGEX = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"
)

LONG_DATE_REGEX = re.compile(
    r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
    re.IGNORECASE,
)

SHORT_DATE_REGEX = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")

WAGE_PERIOD_REGEX = re.compile(
    r"(wage\s*period\s*:\s*)([A-Za-z]+\s+\d{1,2},?\s+\d{4}\s+to\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

FOR_MONTH_YEAR_REGEX = re.compile(r"(\bfor\s+)([A-Za-z]{3,9}\s+\d{4})\b", re.IGNORECASE)

EXCLUDE_CONTEXT_WORDS = [
    "date of birth",
    "dob",
    "tenure of employment",
    "date of appointment",
    "date of joining",
    "entry into employment",
    "appointment",
    "joining",
    "birth",
]


def compile_pattern(user_pattern: str | None) -> re.Pattern:
    if not user_pattern:
        return DEFAULT_DATE_REGEX
    return re.compile(user_pattern)


def parse_date_input(user_str: str | None) -> dict | None:
    """Parse user-provided date string into standardized representations for top and bottom dates,
    wage periods, and month/year headers. Supports ordinals like '2nd November 2026'."""
    if not user_str or not user_str.strip():
        return None
    s = user_str.strip()
    # Strip ordinal suffixes: 2nd -> 2, 1st -> 1, 3rd -> 3, 4th -> 4
    s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    # Normalize multiple spaces
    s = re.sub(r"\s+", " ", s)

    for fmt in (
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            mname = dt.strftime("%B")
            return {
                "dt": dt,
                "day": dt.day,
                "month": dt.month,
                "year": dt.year,
                "month_name": mname,
                "long": f"{mname} {dt.day:02d}, {dt.year}",
                "short_hyphen": dt.strftime("%d-%m-%Y"),
                "short_slash": dt.strftime("%d/%m/%Y"),
                "month_year": f"{mname} {dt.year}",
                "wage_period": f"{mname} 1, {dt.year} to {mname} {last_day}, {dt.year}",
            }
        except ValueError:
            pass
    return None
