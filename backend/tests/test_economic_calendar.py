from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.research.calendars import BLS_SCHEDULE, BEA, FED, CalendarBatch, CalendarError, parse_bea, parse_bls, parse_fed, parse_fed_month
from app.research.models import Agency, CHICAGO

NOW = datetime(2026, 2, 20, 16, tzinfo=UTC)


def event(uid, start, title="Consumer Price Index for January 2026", extra=""):
    return f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260219T120000Z\r\n{start}\r\nSUMMARY:{title}\r\n{extra}END:VEVENT\r\n"


def ics(*events):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//BLS//Calendar//EN\r\n"
            + "".join(events) + "END:VCALENDAR\r\n").encode()


def test_bls_time_normalization_preserves_dst_dates_and_source():
    rows = parse_bls(ics(
        event("winter", "DTSTART;TZID=US-Eastern:20260211T083000"),
        event("summer", "DTSTART;TZID=US/Eastern:20260714T083000", "Producer Price Index for June 2026",
              "URL:https://www.bls.gov/news.release/ppi.nr0.htm\r\n"),
        event("date-only", "DTSTART;VALUE=DATE:20260306", "Employment Situation for February 2026",
              "DTEND;VALUE=DATE:20260307\r\nURL:https://unofficial.example/release\r\n"),
        event("utc", "DTSTART:20260401T020000Z", "Employment Situation (UTC fixture)"),
    ), NOW)
    winter, summer, all_day, utc = rows
    assert winter.scheduled_at_utc == datetime(2026, 2, 11, 13, 30, tzinfo=UTC)
    assert winter.timezone == "US-Eastern"
    assert summer.scheduled_at_utc == datetime(2026, 7, 14, 12, 30, tzinfo=UTC)
    assert {item.scheduled_at_utc.astimezone(CHICAGO).hour for item in (summer, winter)} == {7}
    assert summer.timezone == "US/Eastern" and summer.source_url.endswith("/ppi.nr0.htm")
    assert all_day.event_date == all_day.end_date == date(2026, 3, 6)
    assert all_day.scheduled_at_utc is None and all_day.source_url == BLS_SCHEDULE
    assert utc.display_date == date(2026, 3, 31) and utc.event_date == date(2026, 4, 1)


@pytest.mark.parametrize("value", ["20260308T023000", "20261101T013000"])
def test_ambiguous_or_nonexistent_local_time_is_rejected(value):
    with pytest.raises(CalendarError, match="Ambiguous or nonexistent"):
        parse_bls(ics(event("dst", f"DTSTART;TZID=America/New_York:{value}")), NOW)


def test_bea_parses_report_type_and_official_source_link():
    data = b"""
    <table><thead><tr><th>Year 2026</th></tr></thead><tbody>
    <tr><td class="scheduled-date"><div class="release-date">November 25</div><small>8:30 AM</small></td>
    <td class="release-title">Personal Income and Outlays, October 2026</td>
    <td><a href="/news/2026/october-pio">View</a></td></tr>
    <tr><td class="scheduled-date"><div class="release-date">July 30</div><small>8:30 AM</small></td>
    <td class="release-title">GDP (Advance Estimate), 2nd Quarter 2026</td></tr>
    </tbody></table>
    """
    pce, gdp = parse_bea(data, BEA + "/full", NOW)
    assert pce.source_url == "https://www.bea.gov/news/2026/october-pio" and pce.timezone == "America/New_York"
    assert pce.scheduled_at_utc == datetime(2026, 11, 25, 13, 30, tzinfo=UTC)
    assert gdp.scheduled_at_utc == datetime(2026, 7, 30, 12, 30, tzinfo=UTC)


def test_fed_date_range_and_press_conference_do_not_imply_decision_time():
    data = b"""
    <div id="article"><div class="panel"><h4 class="panel-heading">2026 FOMC Meetings</h4>
    <div class="fomc-meeting"><div class="fomc-meeting__month">April/May</div>
      <div class="fomc-meeting__date">30-1*</div></div></div></div>
    """
    [meeting] = parse_fed(data, NOW)
    assert (meeting.event_date, meeting.end_date) == (date(2026, 4, 30), date(2026, 5, 1))
    assert meeting.scheduled_at_utc is None and meeting.status == "estimated"
    monthly = b"""
    <div id="content">
      <div class="row"><div>2:30 p.m.</div><div>FOMC Press Conference</div><div>9</div></div>
      <div class="row"><div>2:00 p.m.</div><div>FOMC Meeting Two-day meeting Press Conference</div><div>9</div></div>
    </div>
    """
    [conference] = parse_fed_month(monthly, date(2026, 12, 1), FED, NOW)
    assert conference.event_type == "FOMC press conference"
    assert conference.scheduled_at_utc == datetime(2026, 12, 9, 19, 30, tzinfo=UTC)


def test_bls_import_deduplicates_reschedules_and_preserves_cache_on_failure(tmp_path):
    app = create_app(tmp_path / "private.sqlite3")
    service = app.state.economic_calendar
    service.clock = lambda: NOW

    class Blocked:
        calls = 0

        async def load(self, agency, _now):
            assert agency == Agency.BLS
            self.calls += 1
            raise CalendarError("Official source returned HTTP 403.")

    service.provider = blocked = Blocked()
    original = event("fixed", "DTSTART;TZID=America/New_York:20260311T083000", extra="SEQUENCE:0\r\n")
    revised = event("fixed", "DTSTART;TZID=America/New_York:20260312T093000", extra="SEQUENCE:1\r\n")
    cancelled = event("fixed", "DTSTART;TZID=America/New_York:20260312T093000", extra="SEQUENCE:2\r\nSTATUS:CANCELLED\r\n")
    with TestClient(app) as client:
        path = "/api/events?agency=BLS&start=2026-03-01&end=2026-03-31"
        refreshed = client.get(path)
        assert refreshed.json()["sources"][0]["status"] == "error"
        assert client.get(path).status_code == 200 and blocked.calls == 1
        for payload in (ics(original, revised, original), ics(original), ics(cancelled)):
            result = client.post("/api/events/bls/import", content=payload, headers={"Content-Type": "text/calendar"})
            assert result.status_code == 200
        failed = client.post("/api/events/refresh?agency=BLS").json()[0]
        assert failed["status"] == "error" and failed["last_import_at"] and failed["last_success_at"]
        [row] = client.get(path).json()["events"]
        assert row["provider_id"] == "fixed" and row["event_date"] == "2026-03-12" and row["status"] == "cancelled"
        invalid = client.post("/api/events/bls/import", content=b"<html>Access Denied</html>",
                              headers={"Content-Type": "text/calendar"})
        assert invalid.status_code == 422
        assert client.get(path).json()["events"] == [row]


def test_successful_feed_marks_removed_future_event_unverified(tmp_path):
    app = create_app(tmp_path / "portfolio.sqlite3")
    service = app.state.economic_calendar
    service.clock = lambda: NOW
    first = event("first", "DTSTART;VALUE=DATE:20260301")
    omitted = event("omitted", "DTSTART;VALUE=DATE:20260311")
    last = event("last", "DTSTART;VALUE=DATE:20260330")

    class Provider:
        data = ics(first, omitted, last)

        async def load(self, _agency, now):
            return CalendarBatch(parse_bls(self.data, now))

    service.provider = provider = Provider()
    with TestClient(app) as client:
        assert client.post("/api/events/refresh?agency=BLS").status_code == 200
        provider.data = ics(first, last)
        assert client.post("/api/events/refresh?agency=BLS").status_code == 200
        [row] = client.get("/api/events?agency=BLS&start=2026-03-11&end=2026-03-11&refresh=false").json()["events"]
        assert row["status"] == "unverified"
