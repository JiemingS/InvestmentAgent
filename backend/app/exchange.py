from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

NEW_YORK = ZoneInfo("America/New_York")
FIRST_MARKET_DATE = date(1970, 1, 1)
FINALIZATION_DELAY = timedelta(hours=1)


@dataclass(frozen=True)
class Session:
    date: date
    opens: datetime
    closes: datetime

    def is_final(self, at: datetime) -> bool:
        return at >= self.closes + FINALIZATION_DELAY


@lru_cache(maxsize=2)
def _calendar(year: int):
    return xcals.get_calendar(
        "XNYS", start=FIRST_MARKET_DATE.isoformat(), end=f"{year + 1}-12-31",
    )


def market_sessions(start: date, end: date) -> list[Session]:
    start = max(start, FIRST_MARKET_DATE)
    if start > end:
        return []
    schedule = _calendar(end.year).schedule.loc[start.isoformat():end.isoformat()]
    return [
        Session(day.date(), row.open.to_pydatetime(), row.close.to_pydatetime())
        for day, row in schedule.iterrows()
    ]
