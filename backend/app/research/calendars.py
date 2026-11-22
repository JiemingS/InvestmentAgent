from calendar import month_name
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar

from .models import Agency, EASTERN, Event

FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA = "https://www.bea.gov/news/schedule"
BLS = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE = "https://www.bls.gov/schedule/news_release/"
SOURCES = {Agency.FED: FED, Agency.BEA: BEA, Agency.BLS: BLS}
MAX_CALENDAR_BYTES = 2_000_000
MONTHS = {name.casefold(): number for number, name in enumerate(month_name) if name}
MONTHS.update({name[:3]: number for name, number in MONTHS.items()})
BLS_EASTERN_ALIASES = {"US-Eastern", "Eastern Standard Time"}


class CalendarError(ValueError):
    pass


@dataclass
class CalendarBatch:
    events: list[Event]
    warning: str | None = None


def _clean(value: str) -> str:
    return " ".join(str(value).split())


def official_link(base: str, target: str | None) -> str:
    if not target:
        return base
    url = urljoin(base, target)
    parsed = urlsplit(url)
    origin = urlsplit(base)
    if parsed.scheme == "https" and parsed.netloc == origin.netloc:
        return url
    return base


def _event(
    agency: Agency, key: str, event_type: str, title: str, day: date,
    source: str, checked: datetime, *, end: date | None = None,
    when: datetime | None = None, timezone: str = EASTERN.key,
    original: str | None = None, status: str = "confirmed", provider_id: str | None = None,
    sequence: int | None = None, provider_updated_at: datetime | None = None,
) -> Event:
    digest = sha256(key.encode()).hexdigest()[:24]
    return Event(
        id=f"{agency.lower()}-{digest}", agency=agency, event_type=event_type, title=title,
        event_date=day, end_date=end or day, scheduled_at_utc=when, timezone=timezone,
        original_time=original, source_url=source, status=status, provider_id=provider_id,
        sequence=sequence, provider_updated_at=provider_updated_at, last_verified_at=checked,
    )


def _local_utc(value: datetime, zone: ZoneInfo) -> datetime:
    candidates = {
        candidate for fold in (0, 1)
        if (candidate := value.replace(tzinfo=zone, fold=fold).astimezone(UTC))
        .astimezone(zone).replace(tzinfo=None) == value
    }
    if len(candidates) != 1:
        raise CalendarError(f"Ambiguous or nonexistent local release time in {zone.key}.")
    return candidates.pop()


def _clock(day: date, source: str | None) -> datetime | None:
    if not source:
        return None
    value = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.sub(r"\.", "", source.lower()))
    if not value:
        return None
    hour, minute, meridiem = value.groups()
    if not 1 <= int(hour) <= 12:
        raise CalendarError("Invalid published release time.")
    evening = 12 if meridiem == "pm" else 0
    return _local_utc(datetime.combine(day, time((int(hour) % 12) + evening, int(minute or 0))), EASTERN)


def parse_bea(data: bytes, source: str, checked: datetime) -> list[Event]:
    soup = BeautifulSoup(data, "html.parser")
    events = []
    for table in soup.select("table"):
        heading = table.select_one("thead th")
        year = re.search(r"\bYear\s+(\d{4})\b", heading.get_text(" ", strip=True)) if heading else None
        if not year:
            continue
        for row in table.select("tbody tr"):
            subject, published = row.select_one(".release-title"), row.select_one(".release-date")
            if not subject or not published:
                continue
            title = _clean(subject.get_text(" ", strip=True))
            lower = title.casefold()
            if lower.startswith("personal income and outlays"):
                kind = "Personal Income and Outlays / PCE"
            elif re.match(r"^(?:gdp\s*[,(]|gross domestic product\s*[,(])", lower):
                kind = "GDP"
            else:
                continue
            datestr = published.get_text(" ", strip=True)
            day = datetime.strptime(f"{datestr} {year[1]}", "%B %d %Y").date()
            clock = row.select_one(".scheduled-date small")
            original = _clean(clock.get_text(" ", strip=True)) if clock else None
            link = row.select_one("a[href]")
            events.append(_event(
                Agency.BEA, lower, kind, title, day,
                official_link(source, link["href"] if link else None), checked,
                when=_clock(day, original), original=original,
                status="cancelled" if "cancelled" in lower or "canceled" in lower else "confirmed",
            ))
    if not events:
        raise CalendarError("No supported GDP or PCE releases found in the BEA schedule.")
    return events


def parse_fed(data: bytes, checked: datetime) -> list[Event]:
    soup = BeautifulSoup(data, "html.parser")
    events = []
    for panel in soup.select("#article .panel"):
        heading = panel.select_one(".panel-heading")
        year = re.search(r"\b(\d{4})\s+FOMC Meetings", heading.get_text(" ", strip=True)) if heading else None
        if not year:
            continue
        for row in panel.select(".fomc-meeting"):
            month_node = row.select_one(".fomc-meeting__month")
            date_node = row.select_one(".fomc-meeting__date")
            if not month_node or not date_node:
                continue
            month_text = month_node.get_text(" ", strip=True)
            names = [MONTHS.get(name.strip().casefold().rstrip(".")) for name in month_text.split("/")]
            date_text = date_node.get_text(" ", strip=True)
            dates = re.match(r"(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?", date_text)
            if not dates or not all(names):
                continue
            first_month, last_month = names[0], names[-1]
            year_number = int(year[1])
            first = date(year_number, first_month, int(dates[1]))
            last = date(year_number + (last_month < first_month), last_month, int(dates[2] or dates[1]))
            if first > last:
                raise CalendarError("Fed meeting date range is reversed.")
            note = date_text.casefold()
            key = f"meeting:{year_number}:{first_month}"
            if "unscheduled" in note or "notation" in note:
                key += f":{first.day}"
            meeting_status = ("cancelled" if "cancel" in note else
                              "estimated" if first >= checked.astimezone(EASTERN).date() else "confirmed")
            events.append(_event(Agency.FED, key, "FOMC meeting", "FOMC meeting", first, FED, checked,
                                 end=last, original=f"{month_text} {date_text}", status=meeting_status))

            statement = row.select_one('a[href*="/pressreleases/monetary"]')
            if statement:
                events.append(_event(
                    Agency.FED, f"decision:{last}", "FOMC decision", "FOMC policy statement",
                    last, official_link(FED, statement["href"]), checked,
                ))
            minutes = row.select_one(".fomc-meeting__minutes")
            if minutes:
                published = re.search(r"Released\s+([A-Za-z]+ \d{1,2}, \d{4})", minutes.get_text(" ", strip=True))
                if published:
                    day = datetime.strptime(published[1], "%B %d, %Y").date()
                    link = minutes.select_one('a[href$=".htm"]') or minutes.select_one("a[href]")
                    events.append(_event(
                        Agency.FED, f"minutes:{day}", "FOMC minutes", "FOMC meeting minutes",
                        day, official_link(FED, link["href"] if link else None), checked,
                    ))
    if not events:
        raise CalendarError("No FOMC meeting rows found in the official calendar.")
    return events


def parse_fed_month(data: bytes, month: date, source: str, checked: datetime) -> list[Event]:
    soup = BeautifulSoup(data, "html.parser")
    entries = []
    for row in soup.select("#article .row, #content .row"):
        columns = row.find_all("div", recursive=False)
        if len(columns) != 3:
            continue
        clock, title, day = [_clean(part.get_text(" ", strip=True)) for part in columns]
        if not day.isdecimal():
            continue
        normalized = title.casefold()
        if "fomc" not in normalized and "federal open market committee" not in normalized:
            continue
        if normalized.startswith("fomc meeting"):
            continue
        if "minutes" in normalized:
            kind, key, label = "FOMC minutes", "minutes", "FOMC meeting minutes"
        elif "press conference" in normalized:
            kind, key, label = "FOMC press conference", "conference", "FOMC press conference"
        elif "statement" in normalized or "decision" in normalized:
            kind, key, label = "FOMC decision", "decision", "FOMC policy statement"
        else:
            continue
        release = month.replace(day=int(day))
        entries.append(_event(
            Agency.FED, f"{key}:{release}", kind, label, release, source, checked,
            when=_clock(release, clock), original=clock or None,
        ))
    return entries


def _bls_type(title: str) -> str | None:
    value = title.casefold()
    for names, kind in (
        (("consumer price index", "cpi"), "CPI"),
        (("employment situation",), "Employment Situation"),
        (("producer price index", "ppi"), "PPI"),
    ):
        if value.startswith(names):
            return kind
    return None


def parse_bls(data: bytes, checked: datetime) -> list[Event]:
    if len(data) > MAX_CALENDAR_BYTES or not data.lstrip(b"\xef\xbb\xbf\r\n ").startswith(b"BEGIN:VCALENDAR"):
        raise CalendarError("Expected an official BLS iCalendar file up to 2 MB.")
    try:
        calendar = Calendar.from_ical(data)
        if str(calendar.get("VERSION")) != "2.0":
            raise CalendarError("Expected iCalendar version 2.0.")
        events = []
        for component in calendar.walk("VEVENT"):
            title = _clean(component.get("SUMMARY", ""))
            kind = _bls_type(title)
            if kind is None:
                continue
            if component.get("RRULE"):
                raise CalendarError("Recurring BLS events require individually dated releases.")
            field = component.get("DTSTART")
            if field is None:
                raise CalendarError("A supported BLS release is missing DTSTART.")
            value = field.dt
            timezone = str(field.params.get("TZID", ""))
            when = None
            if isinstance(value, datetime):
                if timezone:
                    zone = EASTERN if timezone in BLS_EASTERN_ALIASES else ZoneInfo(timezone)
                    when, day = _local_utc(value.replace(tzinfo=None), zone), value.date()
                elif value.tzinfo is not None:
                    timezone = timezone or getattr(value.tzinfo, "key", str(value.tzinfo))
                    when = value.astimezone(UTC)
                    day = value.date()
                else:
                    when, day = _local_utc(value, EASTERN), value.date()
                timezone = timezone or EASTERN.key
            else:
                day = value
                timezone = EASTERN.key
            ending = component.get("DTEND")
            end = ending.dt - timedelta(days=1) if ending and not isinstance(value, datetime) else day
            if not isinstance(end, date) or isinstance(end, datetime) or end < day:
                raise CalendarError("A BLS all-day event has an invalid end date.")
            uid = _clean(component.get("UID", "")) or None
            stamp = component.get("DTSTAMP")
            revised = stamp.dt.astimezone(UTC) if stamp and isinstance(stamp.dt, datetime) and stamp.dt.tzinfo else None
            component_status = str(component.get("STATUS", "")).upper()
            status = {"TENTATIVE": "estimated", "CANCELLED": "cancelled"}.get(component_status, "confirmed")
            original = value.isoformat()
            if "TZID" in field.params:
                original = f"{value.replace(tzinfo=None).isoformat()} [{field.params['TZID']}]"
            events.append(_event(
                Agency.BLS, uid or f"{kind}:{day}", kind, title, day,
                official_link(BLS_SCHEDULE, str(component.get("URL", ""))), checked,
                end=end, when=when, timezone=timezone, original=original, status=status,
                provider_id=uid, sequence=int(component.get("SEQUENCE", 0)), provider_updated_at=revised,
            ))
    except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError) as error:
        if isinstance(error, CalendarError):
            raise
        raise CalendarError("The BLS iCalendar could not be parsed.") from error
    if not events:
        raise CalendarError("The calendar has no supported BLS CPI, PPI, or Employment Situation releases.")
    return events


async def _download(client: httpx.AsyncClient, source: str, *, accept: str = "text/html") -> bytes:
    try:
        async with client.stream("GET", source, headers={"Accept": accept}, follow_redirects=False) as response:
            if response.status_code != 200:
                raise CalendarError(f"Official source returned HTTP {response.status_code}.")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_CALENDAR_BYTES:
                    raise CalendarError("Official source response exceeded 2 MB.")
            return bytes(content)
    except httpx.HTTPError as error:
        raise CalendarError("The official source could not be reached.") from error


class OfficialCalendars:
    def __init__(self, bls_contact: str | None = None):
        self.user_agent = "PersonalInvestmentAgent/1.0" + (f" (contact: {bls_contact})" if bls_contact else "")

    async def load(self, agency: Agency, checked: datetime) -> CalendarBatch:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": self.user_agent}) as client:
            if agency == Agency.BLS:
                try:
                    return CalendarBatch(parse_bls(await _download(client, BLS, accept="text/calendar"), checked))
                except CalendarError as error:
                    raise CalendarError(f"{error} Import an iCalendar export from BLS if needed.") from error
            if agency == Agency.BEA:
                full = BEA + "/full"
                events = parse_bea(await _download(client, full), full, checked)
                try:
                    next_year = BEA + "/next-year"
                    events.extend(parse_bea(await _download(client, next_year), next_year, checked))
                except (CalendarError, ValueError) as error:
                    return CalendarBatch(events, f"BEA next-year schedule unavailable: {error}")
                return CalendarBatch(events)

            events = {event.id: event for event in parse_fed(await _download(client, FED), checked)}
            month = checked.astimezone(EASTERN).date().replace(day=1)
            warning = None
            for offset in range(3):
                index = month.month - 1 + offset
                target = date(month.year + index // 12, index % 12 + 1, 1)
                url = f"https://www.federalreserve.gov/newsevents/{target.year}-{month_name[target.month].lower()}.htm"
                try:
                    for event in parse_fed_month(await _download(client, url), target, url, checked):
                        previous = events.get(event.id)
                        if event.scheduled_at_utc or not previous:
                            events[event.id] = event
                except (CalendarError, ValueError):
                    if offset == 0:
                        warning = "Fed monthly release times could not be refreshed; FOMC meeting dates were refreshed."
            return CalendarBatch(list(events.values()), warning)
