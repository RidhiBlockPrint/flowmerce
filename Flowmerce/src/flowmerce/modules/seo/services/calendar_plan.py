"""The content calendar: upcoming events and seasons, and the team's schedule for researching, drafting and publishing.

Events are built in (US retail holidays and seasons, plus Diwali and Hanukkah for the years whose dates are listed) or added
by the team. Each event has a lead time: the article for it should be live `lead_days` before the event ("publish by").
Topic research is told about upcoming events, so Flowmerce proposes topics and keywords for what is coming.

A schedule entry asks Flowmerce to do one thing on a day:
  research  start a topic research job focused on the entry's event (topics still need a person's approval)
  draft     start a draft for an approved topic (the entry's own, or the best match for its event)
  publish   once the article is reviewer-approved, put in a request to publish it on that day; a reviewer still authorizes it
Nothing here approves, publishes or bypasses the daily Claude limit: an entry that would go over the limit waits for the next day."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..audit import audit
from ..config import is_brand
from ..db import all_rows, get, now, run
from ..util import HttpError, s, slugify
from . import ai_budget

log = logging.getLogger(__name__)

ACTIONS = ("research", "draft", "publish")
HORIZON_DAYS = 120
PUBLISH_HOUR_LOCAL = 10      # a scheduled publish goes live at 10:00 in the budget's business time zone

# Dates that follow the moon, for the years we know. Other years simply have no entry.
_DIWALI = {2026: "2026-11-08", 2027: "2027-10-29", 2028: "2028-10-17"}
_HANUKKAH = {2026: "2026-12-04", 2027: "2027-12-24", 2028: "2028-12-12"}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th given weekday (Mon=0) of a month; n=-1 is the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def builtin_events(year: int) -> list[dict[str, Any]]:
    """The built-in events of one year: (name, date, lead days, what it is good for)."""
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    rows: list[tuple[str, date, int, str]] = [
        ("New Year's Day", date(year, 1, 1), 30, "Fresh-start tables, New Year hosting"),
        ("Valentine's Day", date(year, 2, 14), 35, "Dinner for two, red and pink linens, gifting"),
        ("Spring begins", date(year, 3, 20), 30, "Spring table refresh, florals, brunch"),
        ("Easter", _easter(year), 35, "Easter brunch tables, pastel and floral linens"),
        ("Wedding season", date(year, 5, 1), 45, "Wedding and event tables, bulk napkins, gifts"),
        ("Mother's Day", _nth_weekday(year, 5, 6, 2), 35, "Gifts for mom, brunch tables"),
        ("Memorial Day", _nth_weekday(year, 5, 0, -1), 21, "Outdoor dining, summer start"),
        ("Father's Day", _nth_weekday(year, 6, 6, 3), 28, "Gifts, grilling and outdoor tables"),
        ("Independence Day", date(year, 7, 4), 28, "Fourth of July picnics and patio tables"),
        ("Labor Day", _nth_weekday(year, 9, 0, 1), 21, "End-of-summer gatherings"),
        ("Fall begins", date(year, 9, 22), 30, "Fall table refresh, harvest colors"),
        ("Halloween", date(year, 10, 31), 35, "Halloween parties and autumn decor"),
        ("Thanksgiving", thanksgiving, 45, "Thanksgiving table sizes, sets, hosting and care"),
        ("Black Friday", thanksgiving + timedelta(days=1), 30, "Gift guides and holiday shopping"),
        ("Winter begins", date(year, 12, 21), 30, "Cozy winter tables and bedding"),
        ("Christmas", date(year, 12, 25), 50, "Christmas tables, red and green linens, gifting"),
        ("New Year's Eve", date(year, 12, 31), 30, "Party tables and hosting"),
    ]
    if year in _DIWALI:
        rows.append(("Diwali", date.fromisoformat(_DIWALI[year]), 35, "Festive tables, gifting, Indian craft stories"))
    if year in _HANUKKAH:
        rows.append(("Hanukkah begins", date.fromisoformat(_HANUKKAH[year]), 30, "Holiday hosting and gifting"))
    return [{"key": f"{slugify(name)}-{year}", "name": name, "date": d.isoformat(), "lead_days": lead,
             "publish_by": (d - timedelta(days=lead)).isoformat(), "note": note, "builtin": True, "brand_id": ""} for name, d, lead, note in rows]


def _custom(brand_id: str | None) -> list[dict[str, Any]]:
    rows = all_rows("SELECT * FROM calendar_events WHERE brand_id = '' OR brand_id = ? ORDER BY date", brand_id or "")
    return [{"key": f"custom-{r['id']}", "id": r["id"], "name": r["name"], "date": r["date"], "lead_days": r["lead_days"],
             "publish_by": (date.fromisoformat(r["date"]) - timedelta(days=r["lead_days"])).isoformat(), "note": r["note"],
             "builtin": False, "brand_id": r["brand_id"]} for r in rows]


def events_between(brand_id: str | None, start: str, end: str) -> list[dict[str, Any]]:
    """Every event whose date or publish-by date falls in [start, end], sorted by date."""
    y0, y1 = int(start[:4]), int(end[:4])
    out = [e for y in range(y0, y1 + 2) for e in builtin_events(y)] + _custom(brand_id)
    return sorted((e for e in out if start <= e["date"] <= end or start <= e["publish_by"] <= end), key=lambda e: (e["date"], e["name"]))


def find_event(brand_id: str | None, key: str) -> dict[str, Any] | None:
    if key.startswith("custom-"):
        return next((e for e in _custom(brand_id) if e["key"] == key), None)
    m = re.search(r"-(\d{4})$", key)
    return next((e for e in builtin_events(int(m.group(1))) if e["key"] == key), None) if m else None


def upcoming(brand_id: str | None, days: int = HORIZON_DAYS) -> list[dict[str, Any]]:
    """Events still ahead within `days`, soonest first."""
    start = ai_budget.today()
    end = (date.fromisoformat(start) + timedelta(days=days)).isoformat()
    return [e for e in events_between(brand_id, start, end) if e["date"] >= start]


def upcoming_for_prompt(brand_id: str) -> list[dict[str, Any]]:
    """What topic research is told: upcoming events whose article can still be live in time (publish-by not long past)."""
    soon = (date.fromisoformat(ai_budget.today()) - timedelta(days=7)).isoformat()
    return [{k: e[k] for k in ("date", "name", "publish_by", "note")} for e in upcoming(brand_id) if e["publish_by"] >= soon]


# ---------------------------------------------------------------- the team's own events

def _day(v: Any, label: str) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise HttpError(400, f"{label} must be a date (YYYY-MM-DD).")


def add_event(user: dict, body: dict) -> dict[str, Any]:
    brand_id = str(body.get("brand") or "")
    if brand_id and not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    name = s(body.get("name"), 120).strip()
    if not name:
        raise HttpError(400, "Give the event a name.")
    try:
        lead = int(body.get("lead_days", 30))
    except (TypeError, ValueError):
        raise HttpError(400, "lead_days must be a whole number.")
    if not 0 <= lead <= 180:
        raise HttpError(400, "Lead time must be 0 to 180 days.")
    eid = run("INSERT INTO calendar_events (brand_id, name, date, lead_days, note, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
              brand_id, name, _day(body.get("date"), "date"), lead, s(body.get("note"), 300).strip(), user["id"], now()).last_id
    audit(user, "calendar.event_add", "calendar_event", eid, brand_id, name)
    return next(e for e in _custom(brand_id or None) if e.get("id") == eid)


def delete_event(user: dict, eid: int) -> None:
    r = get("SELECT * FROM calendar_events WHERE id = ?", eid)
    if not r:
        raise HttpError(404, "Event not found.")
    run("DELETE FROM calendar_events WHERE id = ?", eid)
    audit(user, "calendar.event_delete", "calendar_event", eid, r["brand_id"], r["name"])


# ---------------------------------------------------------------- the schedule

def list_schedule(brand_id: str | None, start: str, end: str) -> list[dict[str, Any]]:
    where, args = "cs.run_on BETWEEN ? AND ?", [start, end]
    if brand_id:
        where += " AND cs.brand_id = ?"
        args.append(brand_id)
    return all_rows(f"""SELECT cs.*, t.title AS topic_title, a.title AS article_title, a.status AS article_status
                        FROM content_schedule cs LEFT JOIN topics t ON t.id = cs.topic_id LEFT JOIN articles a ON a.id = cs.article_id
                        WHERE {where} ORDER BY cs.run_on, cs.id""", *args)


def add_entry(user: dict, body: dict) -> dict[str, Any]:
    brand_id = str(body.get("brand") or "")
    if not is_brand(brand_id):
        raise HttpError(400, "Pick a brand.")
    action = str(body.get("action") or "")
    if action not in ACTIONS:
        raise HttpError(400, f"action must be one of {', '.join(ACTIONS)}.")
    run_on = _day(body.get("run_on"), "run_on")
    if run_on < ai_budget.today():
        raise HttpError(400, "Pick today or a later day.")
    ev = find_event(brand_id, str(body.get("event_key") or "")) if body.get("event_key") else None
    if body.get("event_key") and not ev:
        raise HttpError(400, "That event is not on the calendar.")
    topic_id = int(body["topic_id"]) if body.get("topic_id") else None
    article_id = int(body["article_id"]) if body.get("article_id") else None
    focus = s(body.get("focus"), 500).strip()
    if action == "research" and not (ev or focus):
        raise HttpError(400, "Say what to research: pick an event or write a focus.")
    if action == "draft":
        if topic_id:
            t = get("SELECT status FROM topics WHERE id = ? AND brand_id = ?", topic_id, brand_id)
            if not t:
                raise HttpError(404, "That topic does not exist for this brand.")
        elif not ev:
            raise HttpError(400, "Pick an approved topic, or an event whose approved topic Flowmerce should draft.")
    if action == "publish":
        if not article_id or not get("SELECT 1 FROM articles WHERE id = ? AND brand_id = ?", article_id, brand_id):
            raise HttpError(400, "Pick the article to publish.")
    t = now()
    eid = run("""INSERT INTO content_schedule (brand_id, action, run_on, event_key, event_name, focus, topic_id, article_id, status, message, created_by, created_at, updated_at)
                 VALUES (?,?,?,?,?,?,?,?, 'planned', '', ?,?,?)""",
              brand_id, action, run_on, ev["key"] if ev else "", ev["name"] if ev else "", focus, topic_id, article_id, user["id"], t, t).last_id
    audit(user, "calendar.schedule_add", "content_schedule", eid, brand_id, f"{action} on {run_on}" + (f" for {ev['name']}" if ev else ""))
    return get("SELECT * FROM content_schedule WHERE id = ?", eid)  # type: ignore[return-value]


def update_entry(user: dict, eid: int, body: dict) -> dict[str, Any]:
    r = get("SELECT * FROM content_schedule WHERE id = ?", eid)
    if not r:
        raise HttpError(404, "Schedule entry not found.")
    if "status" in body:
        if body["status"] not in ("planned", "skipped"):
            raise HttpError(400, "An entry can only be skipped or planned again.")
        if r["status"] == "done":
            raise HttpError(409, "This entry already ran.")
        run("UPDATE content_schedule SET status = ?, message = '', updated_at = ? WHERE id = ?", body["status"], now(), eid)
    if "run_on" in body:
        day = _day(body["run_on"], "run_on")
        if day < ai_budget.today():
            raise HttpError(400, "Pick today or a later day.")
        if r["status"] == "done":
            raise HttpError(409, "This entry already ran.")
        run("UPDATE content_schedule SET run_on = ?, updated_at = ? WHERE id = ?", day, now(), eid)
    audit(user, "calendar.schedule_update", "content_schedule", eid, r["brand_id"], ", ".join(sorted(body)))
    return get("SELECT * FROM content_schedule WHERE id = ?", eid)  # type: ignore[return-value]


def delete_entry(user: dict, eid: int) -> None:
    r = get("SELECT * FROM content_schedule WHERE id = ?", eid)
    if not r:
        raise HttpError(404, "Schedule entry not found.")
    run("DELETE FROM content_schedule WHERE id = ?", eid)
    audit(user, "calendar.schedule_delete", "content_schedule", eid, r["brand_id"], f"{r['action']} on {r['run_on']}")


def suggest_plan(user: dict, brand_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Plan research and drafting for every upcoming event that has no entries yet. Research goes about three weeks before the
    publish-by date and drafting three days after research. At most one Claude task is placed on any day (across brands),
    so the plan stays inside an even daily limit instead of piling work on one day."""
    if not is_brand(brand_id):
        raise HttpError(400, "Unknown brand.")
    today_s = ai_budget.today()
    taken = {r["run_on"] for r in all_rows("SELECT run_on FROM content_schedule WHERE status = 'planned' AND action IN ('research','draft')")}
    planned = {r["event_key"] for r in all_rows("SELECT DISTINCT event_key FROM content_schedule WHERE brand_id = ? AND event_key != ''", brand_id)}

    def free_day(wanted: str, also_taken: str = "") -> str:
        d = max(wanted, today_s)
        while d in taken or d == also_taken:
            d = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        return d

    made: list[dict[str, Any]] = []
    for ev in upcoming(brand_id, days):
        if ev["key"] in planned or ev["publish_by"] < today_s:
            continue
        research = free_day((date.fromisoformat(ev["publish_by"]) - timedelta(days=21)).isoformat())
        draft = free_day((date.fromisoformat(research) + timedelta(days=3)).isoformat(), research)
        if draft > ev["publish_by"]:
            continue   # too late to research and draft before the article should be live; no day is reserved
        taken.update((research, draft))
        for action, day in (("research", research), ("draft", draft)):
            made.append(add_entry(user, {"brand": brand_id, "action": action, "run_on": day, "event_key": ev["key"]}))
    return made


# ---------------------------------------------------------------- running due entries (called by the scheduler)

def _finish(eid: int, status: str, message: str, job_id: str | None = None) -> None:
    run("UPDATE content_schedule SET status = ?, message = ?, job_id = COALESCE(?, job_id), updated_at = ? WHERE id = ?",
        status, s(message, 500), job_id, now(), eid)


def _matching_topic(brand_id: str, event_name: str) -> dict[str, Any] | None:
    """The topic without an article that best matches an event's name (most shared words). Approved topics win; otherwise a
    proposed or validated one (from the event's research task) is used, and the drafting task approves it automatically."""
    words = {w for w in re.findall(r"[a-z0-9]+", event_name.lower()) if len(w) > 2 and w not in ("day", "begins", "season")}
    best, score = None, 0
    rows = all_rows("""SELECT * FROM topics WHERE brand_id = ? AND status IN ('approved','validated','proposed')
                       AND id NOT IN (SELECT topic_id FROM articles WHERE topic_id IS NOT NULL)
                       ORDER BY CASE status WHEN 'approved' THEN 0 WHEN 'validated' THEN 1 ELSE 2 END, updated_at DESC""", brand_id)
    for t in rows:
        n = len(words & set(re.findall(r"[a-z0-9]+", f"{t['title']} {t['primary_keyword']} {t['secondary_keywords']}".lower())))
        if n > score:
            best, score = t, n
    return best


def _publish_at(day: str) -> str:
    local = datetime.fromisoformat(f"{day}T{PUBLISH_HOUR_LOCAL:02d}:00:00")
    return (local - ai_budget.UTC_OFFSET).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def run_due(limit: int = 50) -> int:
    """Run planned entries whose day has come. Returns how many ran. An AI entry that does not fit today's Claude limit
    stays planned (it runs on a later tick); a publish entry waits until its article is reviewer-approved."""
    from . import ai_jobs, publishing   # imported here: both import this module
    done = 0
    today_s = ai_budget.today()
    # AI work runs on (or after) its day; a publish request must be made BEFORE its day, as soon as the article is approved.
    due = all_rows("""SELECT * FROM content_schedule WHERE status = 'planned'
                      AND ((action IN ('research','draft') AND run_on <= ?) OR action = 'publish') ORDER BY run_on, id LIMIT ?""", today_s, limit)
    for e in due:
        try:
            if e["action"] == "publish":
                done += _run_publish(e, today_s, publishing)
                continue
            if e["action"] == "research":
                focus = "; ".join(x for x in (f"Upcoming: {e['event_name']}" if e["event_name"] else "", e["focus"]) if x)
                job, _ = ai_jobs.create_job(None, e["brand_id"], "topic_research", {"focus": focus})
            else:
                from . import autopilot
                tid = e["topic_id"]
                if not tid:
                    t = _matching_topic(e["brand_id"], e["event_name"])
                    if not t:
                        run("UPDATE content_schedule SET message = ?, updated_at = ? WHERE id = ?",
                            f"Waiting: no topic for {e['event_name']} yet. Its research task proposes them.", now(), e["id"])
                        continue
                    tid = t["id"]
                    run("UPDATE content_schedule SET topic_id = ? WHERE id = ?", tid, e["id"])
                ap = autopilot.start_from_topic(e["created_by"], e["brand_id"], tid, f"calendar drafting task for {e['event_name'] or e['run_on']}")
                _finish(e["id"], "done", "Writing the draft; it will be approved and kept in Flowmerce until it is scheduled.", ap["draft_job_id"])
                done += 1
                continue
            _finish(e["id"], "done", "AI job started", job["id"])
            done += 1
        except HttpError as err:
            if err.code in ("daily_limit", "paused", "pending_setup"):
                run("UPDATE content_schedule SET message = ?, updated_at = ? WHERE id = ?", f"Waiting: {err.message}", now(), e["id"])
            else:
                _finish(e["id"], "failed", err.message)
        except Exception as err:  # noqa: BLE001 — one bad entry must not stop the others; it is recorded on the entry
            log.exception("Schedule entry %s failed", e["id"])
            _finish(e["id"], "failed", f"Unexpected error: {type(err).__name__}")
    return done


def _run_publish(e: dict[str, Any], today_s: str, publishing: Any) -> int:
    a = get("SELECT * FROM articles WHERE id = ?", e["article_id"]) if e["article_id"] else None
    if not a:
        _finish(e["id"], "failed", "The article no longer exists.")
        return 0
    if a["status"] in ("publish_requested", "scheduled", "published"):
        _finish(e["id"], "done", f"Already {a['status'].replace('_', ' ')}.")
        return 1
    if a["status"] != "approved" or a["approved_hash"] != a["content_hash"]:
        run("UPDATE content_schedule SET message = ?, updated_at = ? WHERE id = ?",
            "Waiting: the article needs reviewer approval before a publish request can be made.", now(), e["id"])
        return 0
    user = get("SELECT * FROM users WHERE id = ?", e["created_by"]) if e["created_by"] else None
    if not user:
        _finish(e["id"], "failed", "The person who scheduled this no longer exists; request publishing from the article.")
        return 0
    when = _publish_at(e["run_on"])
    if e["run_on"] < today_s or datetime.fromisoformat(when.replace("Z", "+00:00")) < datetime.now(timezone.utc) + timedelta(minutes=15):
        _finish(e["id"], "failed", "The publish day has passed; request publishing from the article.")
        return 0
    publishing.request_publish(user, a["id"], "schedule", when, f"From the content calendar ({e['run_on']})")
    _finish(e["id"], "done", "Publish request made; a reviewer must authorize it.")
    return 1
