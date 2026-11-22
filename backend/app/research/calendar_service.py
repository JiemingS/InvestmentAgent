import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..db import connect
from .calendars import CalendarBatch, OfficialCalendars, SOURCES, parse_bls
from .models import Agency, CalendarResult, CalendarStatus, CHICAGO, Event

REFRESH_INTERVAL = timedelta(days=1)
RETRY_INTERVAL = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)


class CalendarService:
    def __init__(
        self, database: Path, provider: OfficialCalendars, clock: Callable[[], datetime] | None = None,
    ):
        self.database = database
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self.locks = {agency: asyncio.Lock() for agency in Agency}

    def statuses(self, agencies: list[Agency]) -> list[CalendarStatus]:
        with connect(self.database) as connection:
            sources = []
            for agency in agencies:
                row = connection.execute("SELECT * FROM calendar_sync WHERE agency = ?", (agency,)).fetchone()
                coverage = connection.execute(
                    """SELECT MIN(display_date), MAX(display_end)
                       FROM economic_events WHERE agency = ? AND status != 'unverified'""", (agency,),
                ).fetchone()
                sources.append(CalendarStatus(
                    source_url=SOURCES[agency], coverage_start=coverage[0], coverage_end=coverage[1],
                    **(dict(row) if row else {"agency": agency}),
                ))
        return sources

    def events(self, start: date, end: date, agencies: list[Agency]) -> CalendarResult:
        with connect(self.database) as connection:
            placeholders = ",".join("?" for _ in agencies)
            rows = connection.execute(
                f"""
                SELECT * FROM economic_events
                WHERE agency IN ({placeholders}) AND display_date <= ? AND display_end >= ?
                ORDER BY display_date, scheduled_at_utc NULLS LAST, agency, title
                """,
                (*agencies, end.isoformat(), start.isoformat()),
            )
            events = [Event.model_validate(dict(row)) for row in rows]
        return CalendarResult(events=events, sources=self.statuses(agencies))

    async def refresh(self, agencies: list[Agency], *, force: bool = False) -> list[CalendarStatus]:
        await asyncio.gather(*(self._refresh_agency(agency, force) for agency in agencies))
        return self.statuses(agencies)

    async def refresh_daily(self) -> None:
        while True:
            await asyncio.sleep(REFRESH_INTERVAL.total_seconds())
            try:
                await self.refresh(list(Agency))
            except Exception:
                LOGGER.exception("Daily calendar refresh failed")

    async def _refresh_agency(self, agency: Agency, force: bool) -> None:
        async with self.locks[agency]:
            now = self.clock()
            [status] = self.statuses([agency])
            activity = max(
                (value for value in (status.last_attempt_at, status.last_import_at) if value is not None),
                default=None,
            )
            interval = RETRY_INTERVAL if status.status in ("error", "partial") else REFRESH_INTERVAL
            if not force and activity and now - activity < interval:
                return
            try:
                async with asyncio.timeout(24):
                    batch = await self.provider.load(agency, now)
                if not batch.events:
                    raise ValueError("No supported events were returned.")
            except (TimeoutError, ValueError) as error:
                message = str(error) or "Official calendar request timed out."
                self._record_failure(agency, now, message)
                return
            self._save(agency, batch, now, imported=False)

    async def import_bls(self, data: bytes) -> list[CalendarStatus]:
        async with self.locks[Agency.BLS]:
            now = self.clock()
            events = parse_bls(data, now)
            self._save(Agency.BLS, CalendarBatch(events), now, imported=True)
            return self.statuses([Agency.BLS])

    def _record_failure(self, agency: Agency, now: datetime, message: str) -> None:
        with connect(self.database, write=True) as connection:
            connection.execute(
                """
                INSERT INTO calendar_sync(agency, last_attempt_at, status, error_message)
                VALUES (?, ?, 'error', ?)
                ON CONFLICT(agency) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at, status='error', error_message=excluded.error_message
                """,
                (agency, now.isoformat(), message),
            )

    def _save(self, agency: Agency, batch: CalendarBatch, now: datetime, *, imported: bool) -> None:
        stamp = now.isoformat()
        with connect(self.database, write=True) as connection:
            for event in batch.events:
                previous = connection.execute("SELECT * FROM economic_events WHERE id = ?", (event.id,)).fetchone()
                if previous:
                    old = Event.model_validate(dict(previous))
                    if _older_revision(event, old):
                        continue
                    if (
                        event.event_date == old.event_date and event.scheduled_at_utc is None
                        and old.scheduled_at_utc and event.agency == Agency.FED
                    ):
                        event = event.model_copy(update={
                            "scheduled_at_utc": old.scheduled_at_utc, "original_time": old.original_time,
                            "source_url": old.source_url,
                        })
                values = event.model_dump(mode="json")
                values.update(
                    display_date=event.display_date.isoformat(),
                    display_end=(event.display_date if event.scheduled_at_utc else event.end_date).isoformat(),
                )
                columns = ", ".join(values)
                parameters = ", ".join(f":{key}" for key in values)
                assignments = ", ".join(f"{key}=excluded.{key}" for key in values if key != "id")
                connection.execute(
                    f"INSERT INTO economic_events ({columns}) VALUES ({parameters}) "
                    f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                    values,
                )

            if not imported and not batch.warning:
                # Only events inside the current feed's future coverage can be marked unverified.
                today = now.astimezone(CHICAGO).date().isoformat()
                start = min(event.display_date for event in batch.events).isoformat()
                end = max(event.display_date for event in batch.events).isoformat()
                connection.execute(
                    """
                    UPDATE economic_events SET status = 'unverified'
                    WHERE agency = ? AND display_date BETWEEN ? AND ?
                      AND status IN ('confirmed', 'estimated')
                      AND id NOT IN (SELECT value FROM json_each(?))
                    """,
                    (agency, max(today, start), end, json.dumps([event.id for event in batch.events])),
                )
            status = "imported" if imported else "partial" if batch.warning else "ok"
            connection.execute(
                """
                INSERT INTO calendar_sync VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agency) DO UPDATE SET
                    last_attempt_at=COALESCE(excluded.last_attempt_at, calendar_sync.last_attempt_at),
                    last_success_at=excluded.last_success_at,
                    last_import_at=COALESCE(excluded.last_import_at, calendar_sync.last_import_at),
                    status=excluded.status, error_message=excluded.error_message
                """,
                (agency, None if imported else stamp, stamp, stamp if imported else None, status, batch.warning),
            )


def _older_revision(incoming: Event, current: Event) -> bool:
    if incoming.sequence is None or current.sequence is None:
        return False
    if incoming.sequence != current.sequence:
        return incoming.sequence < current.sequence
    return bool(
        incoming.provider_updated_at and current.provider_updated_at
        and incoming.provider_updated_at < current.provider_updated_at
    )
