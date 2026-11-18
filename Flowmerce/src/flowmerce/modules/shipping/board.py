"""The Shipping page: one cached snapshot of ops.flow_board, turned into every figure the page shows.

Rules (agreed with operations, ported from the original tracker so the numbers match):
  * Not dispatched yet: the clock starts at the ORDER date (grey 2-3, yellow 4-5, orange 6-8, red 9+ days).
    Dispatched: the clock starts at the DISPATCH date (on track 0-3, yellow 4-5, orange 6-8, red 9+).
    A carrier scan never resets the clock. Delivered parcels leave the active queue.
  * Cancelled and refunded orders are left out of every figure.
  * "Carrier unconfirmed": no carrier update at all. Amazon / unknown carrier: as soon as it is dispatched (Amazon
    never tells Shopify). A named carrier (USPS, DHL, UPS, FedEx...): once NO_SCAN_GRACE_DAYS have passed since dispatch
    without a single scan (Shopify never received its tracking; e.g. # RBP7437, USPS delivered the day before the
    number was entered). There is no delivery data, so a person checks these by hand; they are never counted
    critical or stuck. Parcels that do have carrier updates follow the normal rules. Also unconfirmed: an order older
    than Shopify's 60-day window whose only status is the hub copy's "failure" (no carrier events to show whether it
    came after a delivery, e.g. #4434 delivered by DHL on 9 Oct).
  * Resolved: an order the team marked Delivered / Lost / Returned / Refunded (Shopify does not know), or a parcel the
    carrier reports lost (e.g. DHL "request ... to dispose of the shipment") or returned (Amazon UNDELIVERABLE,
    "returned to sender"). Resolved parcels leave Critical and every active / delay figure; they are listed under
    "Resolved". Delivered parcels, cancelled and fully refunded orders were already left out.
  * No movement: the last carrier scan is 5+ days old (no scan at all is "no scan", not "no movement").
  * Shopify's "delivered" is shown as delivered but is not carrier-confirmed (see rules.status_view).
  * Missing data is reported as unavailable with a reason, never as zero.

Brands: ridhi = store RBP, cpc = store CPC. "all" shows both, each row labelled; nothing is added across brands
except where the page says "all brands".

Privacy: the snapshot holds city and state only (never street, name, e-mail, phone) and a yes/no for "the order
note says DONE" (never the note text).
"""
from __future__ import annotations

import csv
import io
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..seo.db import all_rows, get, now as db_now, run
from ..seo.util import HttpError
from . import amazon_mcf, mcf_sync
from ..seo.integrations.google import service_account_email
from .supabase import SupabaseError, client

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))     # India has no daylight saving: a fixed offset is exact
DAY = 86400

THRESH = {"grey": 2, "yellow": 4, "orange": 6, "red": 9}
NO_MOVE_DAYS = 5
HUB_SCAN_PREFIX = "Shopify shipment status: "   # the one "scan" 105 writes for a hub-only order (no carrier events)
NO_SCAN_GRACE_DAYS = 3          # a named carrier's first scan normally reaches Shopify within 1-2 days of dispatch
PRE_DISPATCH_DAYS = 60          # undispatched orders older than this are not tracked here (see 107_flow_board.sql)
DELIVERED_KEEP_DAYS = 100       # delivered parcels kept in the snapshot (delivery performance looks back 90 days)
CACHE_SECONDS = 20 * 60        # the data changes only when a refresh runs (every 15 min); each refresh reloads it
STALE_HOURS = 2                 # the refresh runs every 15 minutes; 2 hours without success is stale

BRAND_STORE = {"ridhi": "RBP", "cpc": "CPC"}
STORE_BRAND = {v: k for k, v in BRAND_STORE.items()}

RANK = {"red": 0, "orange": 1, "yellow": 2, "grey": 3, "no_scan": 4, "on_track": 5, "unconfirmed": 5,
        "lost": 5, "failed": 5, "delivered": 6}
LABELS = {"on_track": "On track", "grey": "Grey 2-3 days", "yellow": "Yellow 4-5 days", "orange": "Orange 6-8 days",
          "red": "Critical 9+ days", "no_scan": "No scan data", "delivered": "Delivered",
          "unconfirmed": "Carrier unconfirmed", "lost": "Lost (team confirmed)",
          "failed": "Couldn't deliver (team confirmed)"}
ACTIONS = {"on_track": "Continue monitoring.", "grey": "Continue monitoring.",
           "yellow": "Review if the carrier or the promised delivery date shows a problem.",
           "orange": "Prioritise for investigation.", "red": "Add to the urgent escalation list.",
           "no_scan": "Verify the tracking details or wait for the first carrier scan.",
           "delivered": "None. Delivered."}
AGING_KEYS = ("red", "orange", "yellow", "grey", "on_track", "no_scan")
AGING_LABELS = {"red": "Critical 9+", "orange": "Orange 6-8", "yellow": "Yellow 4-5", "grey": "Grey 2-3",
                "on_track": "On track", "no_scan": "No scan"}
MCF_LEVELS = ((10, "critical"), (7, "watch"), (5, "alert"))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TEAM_STATES = ("delivered", "lost", "failed", "in_transit")
OUTCOMES = {"delivered": "Delivered", "lost": "Lost", "returned": "Returned", "refunded": "Refunded"}
LOST_RE = re.compile(r"\bdispos(?:e|al|ed)\b|\bdestroy(?:ed)?\b|\blost\b", re.I)
RETURN_RE = re.compile(r"return(?:ed|ing)?\s+to\s+(?:the\s+)?(?:sender|shipper|seller|origin|amazon)|\brts\b", re.I)
RETURN_RAW = {"RETURNED", "RETURNING", "RETURNED_TO_SENDER", "RETURN_TO_SENDER", "UNDELIVERABLE"}
EXC_TYPES = {
    "carrier_exception": {"label": "Carrier exception", "severity": "high"},
    "stuck": {"label": "No movement", "severity": "high"},
    "missing_tracking": {"label": "Dispatched without tracking number", "severity": "high"},
    "overdue": {"label": "Past promised date", "severity": "medium"},
    "delivered_not_marked": {"label": "Delivered but not marked", "severity": "medium"},
    "duplicate_tracking": {"label": "Duplicate tracking number", "severity": "medium"},
    "amazon_not_in_shopify": {"label": "Shipped by Amazon, unfulfilled in Shopify", "severity": "medium"},
    "amazon_tracking_missing": {"label": "Amazon parcel not on the Shopify order", "severity": "medium"},
}
SORTS = ("priority", "stuck", "order", "oldest")
COLUMNS = ("row_kind,row_id,tracking_id,shipment_id,store,order_id,order_name,placed_at,kind,carrier_name,tracking_number,track_url,"
           "status,raw_status,source,shipped_at,last_scan_at,last_scan_place,last_scan_text,delivered_at,eta,"
           "last_check_ok_at,team_mark,team_mark_at,open_exceptions,total,currency,financial_status,"
           "fulfillment_status,cancelled_at,ship_city,ship_state,note_done")
AMAZON_COLUMNS = "amazon_status,amazon_at,amazon_ref,amazon_tracking,amazon_checked_at"   # from 108_flow_board_amazon.sql
IMPORT_MAX_ROWS = 1000
IMPORT_MAX_BYTES = 512_000


# ------------------------------------------------------------------------------------------------ small helpers
def ts(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def day_end(v: Any) -> datetime | None:
    """A promised delivery DATE counts until the end of that day."""
    if not v or not isinstance(v, str):
        return None
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)


def iso(d: datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d else None


def whole_days(since: datetime | None, now: datetime) -> int | None:
    return None if since is None else max(0, int((now - since).total_seconds() // DAY))


def unconfirmed_carrier(name: str) -> bool:
    c = name.strip().lower()
    return c in ("", "unknown", "unknown carrier") or "amazon" in c


def flow_category(created: datetime | None, dispatched: datetime | None, now: datetime,
                  delivered: bool) -> tuple[str, int | None, str]:
    """(category, days in stage, stage)."""
    if delivered:
        return "delivered", None, "delivered"
    t = THRESH
    if dispatched is None:
        d = whole_days(created, now)
        if d is None:
            return "no_scan", None, "pre_dispatch"
        cat = "red" if d >= t["red"] else "orange" if d >= t["orange"] else "yellow" if d >= t["yellow"] \
            else "grey" if d >= t["grey"] else "on_track"
        return cat, d, "pre_dispatch"
    d = whole_days(dispatched, now) or 0
    cat = "red" if d >= t["red"] else "orange" if d >= t["orange"] else "yellow" if d >= t["yellow"] else "on_track"
    return cat, d, "dispatched"


def brand_stores(brand: str | None) -> tuple[str, ...]:
    if not brand or brand == "all":
        return tuple(BRAND_STORE.values())
    if brand not in BRAND_STORE:
        raise HttpError(400, "Unknown brand.", "bad_request")
    return (BRAND_STORE[brand],)


# ------------------------------------------------------------------------------------------------ snapshot
@dataclass
class Snapshot:
    rows: list[dict[str, Any]]
    feeds: list[dict[str, Any]]
    loaded_at: datetime
    amazon: bool = True          # False until 108_flow_board_amazon.sql has been run
    items: dict[str, set[str]] | None = None             # shipment id -> Shopify line-item ids in that parcel
    replacements: list[dict[str, Any]] | None = None     # orders that say "replacement for #NNNN" (references only)
    reship_notes: set[int] | None = None                 # order ids whose own note says reshipped / resent
    mcf: list[dict[str, Any]] | None = None              # Amazon MCF packages (109); None when not set up


_lock = threading.Lock()
_cache: tuple[float, Snapshot] | None = None
_reloading = threading.Event()


def _board_rows() -> tuple[list[dict[str, Any]], bool]:
    try:
        return _read_board(f"{COLUMNS},{AMAZON_COLUMNS}"), True
    except SupabaseError as e:
        if e.state != "schema_missing" and "amazon" not in (e.message or ""):
            raise
        return _read_board(COLUMNS), False      # 108 not run yet: everything else still works


def _feeds() -> list[dict[str, Any]]:
    try:
        return client().select("feed_freshness", [("select", "*")]).rows
    except SupabaseError:
        return []


def _load() -> Snapshot:
    """The four reads are independent, so they run at the same time (about 10 s instead of 20 s one after another)."""
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="board-load") as pool:
        board_f, feeds_f = pool.submit(_board_rows), pool.submit(_feeds)
        signals_f, mcf_f = pool.submit(_reship_signals), pool.submit(amazon_mcf.load)
        rows, amazon = board_f.result()
        items, replacements, notes = signals_f.result()
        return Snapshot(rows, feeds_f.result(), datetime.now(UTC), amazon, items, replacements, notes, mcf_f.result())


REF_RE = re.compile(r"(?:replace?ment\s+(?:for|of)|reship(?:ped)?\s+(?:for|of)|instead\s+of)\s*(?:order\s*)?#?\s*(?:RBP\s*)?(\d{3,7})", re.I)
RESHIP_RE = re.compile(r"\b(re-?ship(?:ped|ment)?|re-?sen[dt]|sent\s+again|shipped\s+again)\b", re.I)


def _reship_signals() -> tuple[dict[str, set[str]], list[dict[str, Any]], set[int]]:
    """What tells us a parcel was sent again. Each part is optional: a failure leaves it empty, never breaks the page.
    Order notes are read only for orders whose note or tags mention replacement / reshipping; only the order number they
    refer to (and a yes/no) is kept, the text is dropped at once."""
    items: dict[str, set[str]] = {}
    try:
        c = client()
        last: str | None = None
        while True:
            p = [("select", "id,items"), ("order", "id.asc")]
            if last:
                p.append(("id", f"gt.{last}"))
            page = c.select("shipments", p, limit=1000).rows
            for x in page:
                items[x["id"]] = {str(i.get("item_id")) for i in (x.get("items") or []) if isinstance(i, dict) and i.get("item_id")}
            if len(page) < 1000:
                break
            last = page[-1]["id"]
    except SupabaseError:
        items = {}
    replacements: list[dict[str, Any]] = []
    notes: set[int] = set()
    try:
        from .supabase import public_client
        rows = public_client().select("orders", [
            ("select", "id,name,store,placed_at,tags:raw->>tags,note:raw->>note"),
            ("or", "(raw->>tags.ilike.*replace*,raw->>note.ilike.*replace*,raw->>note.ilike.*reship*,"
                   "raw->>note.ilike.*resen*,raw->>note.ilike.*re-ship*,raw->>note.ilike.*re-sen*,raw->>note.ilike.*again*)")],
            limit=1000).rows
        for r in rows:
            text = f"{r.get('note') or ''} {r.get('tags') or ''}"
            refs = sorted({m for m in REF_RE.findall(text)})
            if refs:
                replacements.append({"id": r["id"], "name": r.get("name"), "store": r.get("store"),
                                     "placed_at": r.get("placed_at"), "refs": refs})
            elif RESHIP_RE.search(r.get("note") or ""):
                notes.add(int(r["id"]))
    except Exception:  # noqa: BLE001 - optional signal
        pass
    return items, replacements, notes


def _read_board(columns: str) -> list[dict[str, Any]]:
    c = client()
    cutoff = (datetime.now(UTC) - timedelta(days=DELIVERED_KEEP_DAYS)).date().isoformat()   # a plain date: safe inside or=(...)
    rows: list[dict[str, Any]] = []
    last: str | None = None
    while True:   # keyset paging: Supabase caps a page at 1000 rows and offsets get slow
        p = [("select", columns), ("order", "row_id.asc"),
             ("or", f"(status.is.null,status.neq.delivered,delivered_at.gt.{cutoff})")]
        if last is not None:
            p.append(("row_id", f"gt.{last}"))
        page = c.select("flow_board", p, limit=1000).rows
        rows += page
        if len(page) < 1000:
            break
        last = page[-1]["row_id"]
    return rows


def snapshot(force: bool = False) -> Snapshot:
    """The cached snapshot. Loading it reads the whole board (several seconds), so a page never waits for it when a
    saved copy exists: an old copy is served while a fresh one loads in the background. Only the very first read (or
    force=True, used right after a refresh) waits. A failed read raises SupabaseError and is never cached."""
    global _cache
    if not force:
        cached = _cache
        if cached:
            if time.time() - cached[0] >= CACHE_SECONDS:
                reload_in_background()
            return cached[1]
    with _lock:
        if not force and _cache:
            return _cache[1]
        snap = _load()
        _cache = (time.time(), snap)
        return snap


def reload_in_background() -> None:
    if _reloading.is_set():
        return
    _reloading.set()

    def work() -> None:
        try:
            snapshot(force=True)
        except Exception:  # noqa: BLE001 - the saved copy stays in use; the next request tries again
            pass
        finally:
            _reloading.clear()
    threading.Thread(target=work, name="shipping-board-reload", daemon=True).start()


def forget() -> None:
    global _cache
    with _lock:
        _cache = None


def apply_mark(tracking_id: str, mark: str | None) -> None:
    """Show a team mark at once in the saved copy (the next refresh reloads it from Supabase anyway)."""
    cached = _cache
    if not cached:
        return
    at = datetime.now(UTC).isoformat()
    for r in cached[1].rows:
        if r.get("tracking_id") == tracking_id:
            r["team_mark"], r["team_mark_at"] = mark, at if mark else None


# ------------------------------------------------------------------------------------------------ enrichment
@dataclass
class Dataset:
    rows: list[dict[str, Any]]          # after exclusions (cancelled, refunded) and without reshipped parcels
    everything: list[dict[str, Any]]    # before exclusions (order detail)
    now: datetime
    brand: str
    snap: Snapshot
    marks: dict[tuple[str, int], dict[str, Any]]
    reshipped: list[dict[str, Any]] = None  # type: ignore[assignment]  # old parcels the team sent again
    resolved: list[dict[str, Any]] = None   # type: ignore[assignment]  # delivered / lost / returned / refunded

    @property
    def active(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["cat"] != "delivered"]


def _enrich(s: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    status = (s.get("status") or "").lower()
    if status == "expired":
        return None                     # tracking closed without an outcome: nothing to act on
    carrier = s.get("carrier_name") or ""
    tracking = s.get("tracking_number") or ""
    created, shipped = ts(s.get("placed_at")), ts(s.get("shipped_at"))
    last_scan, delivered_at = ts(s.get("last_scan_at")), ts(s.get("delivered_at"))
    delivered = status == "delivered"
    cat, days, stage = flow_category(created, shipped if s["row_kind"] != "order" else None, now, delivered)
    no_data = status in ("", "pending") and last_scan is None
    # No carrier data: Amazon (or an unnamed carrier) tells neither Shopify nor Flowmerce about delivery, so a person
    # checks it. A named carrier whose first scan never reached Shopify after NO_SCAN_GRACE_DAYS is the same case: the
    # delay clock would call it critical with no evidence. Only once dispatched: a package not shipped yet keeps its clock.
    via_amazon = unconfirmed_carrier(carrier) or s.get("kind") == "mcf" or s["row_kind"] == "amazon"
    never_scanned = s["row_kind"] == "tracking" and (whole_days(shipped, now) or 0) >= NO_SCAN_GRACE_DAYS
    # Orders older than Shopify's 60-day window reach Flowmerce only through the hub's copy: one status word, no carrier
    # events. A lone "failure" there cannot be told apart from DHL's stray FAILURE after delivery (e.g. #4434: DHL
    # delivered 9 Oct, Shopify's last word "failure" on 25 Oct), so it is checked by hand, never counted critical.
    hub_failure = (status == "exception" and s["row_kind"] == "tracking"
                   and (s.get("last_scan_text") or "").startswith(HUB_SCAN_PREFIX))
    unconfirmed = stage == "dispatched" and ((no_data and (via_amazon or never_scanned)) or hub_failure)
    scan_age = whole_days(last_scan, now)
    no_move = cat != "delivered" and not unconfirmed and scan_age is not None and scan_age >= NO_MOVE_DAYS
    exc = ""
    if status in ("exception", "returned") and not (unconfirmed and hub_failure):
        exc = (s.get("raw_status") or status).lower()
    shown = "unconfirmed" if cat != "delivered" and unconfirmed else cat
    manual = None
    mark = (s.get("team_mark") or "").lower()
    if unconfirmed and mark in TEAM_STATES:
        manual = {"status": mark, "at": s.get("team_mark_at")}
        shown = {"delivered": "delivered", "lost": "lost", "failed": "failed"}.get(mark, shown)
    fin = (s.get("financial_status") or "").upper()
    return {
        **s,
        "brand": STORE_BRAND.get(s.get("store") or "", s.get("store")),
        "order_number": s.get("order_name") or str(s.get("order_id")),
        "carrier_name": carrier,
        "tracking_number": tracking,
        "normalized_tracking_status": status,
        "created": created, "shipped": None if s["row_kind"] == "order" else shipped,
        "lastScan": last_scan, "deliveredAt": delivered_at, "expected": day_end(s.get("eta")),
        "cat": shown, "agingCat": cat, "days": days, "stage": stage, "scanAge": scan_age, "noMove": no_move,
        "unconfirmed": unconfirmed, "hubFailure": unconfirmed and hub_failure, "exc": exc, "manual": manual,
        "missingTracking": s["row_kind"] == "shipment" or (s["row_kind"] in ("tracking", "amazon") and not tracking),
        "excluded": "cancelled" if s.get("cancelled_at") else "refunded" if fin == "REFUNDED" else None,
        "key": f"{s['row_kind']}:{s['row_id']}",
    }


def _marks(stores: tuple[str, ...]) -> dict[tuple[str, int], dict[str, Any]]:
    ph = ",".join("?" for _ in stores)
    out: dict[tuple[str, int], dict[str, Any]] = {}
    try:
        for r in all_rows(f"SELECT * FROM shipping_order_marks WHERE store IN ({ph})", *stores):
            out[(r["store"], int(r["order_id"]))] = r
    except Exception:  # noqa: BLE001 - team marks are an extra; a missing table must not break the page
        pass
    return out


def carrier_outcome(r: dict[str, Any]) -> str | None:
    """'lost' / 'returned' when the carrier's own last word says so (a dispatched parcel only)."""
    if r["cat"] == "delivered" or r["stage"] != "dispatched":
        return None
    text = r.get("last_scan_text") or ""
    if LOST_RE.search(text):
        return "lost"
    if (r["normalized_tracking_status"] == "returned" or (r.get("raw_status") or "").upper() in RETURN_RAW
            or RETURN_RE.search(text)):
        return "returned"
    return None


def _mark_resolved(everything: list[dict[str, Any]], marks: dict[tuple[str, int], dict[str, Any]]) -> None:
    """The team's outcome for the whole order wins; then a team "lost" mark on a parcel; then the carrier's word."""
    for r in everything:
        if r["cat"] == "delivered":
            continue
        try:
            m = marks.get((r.get("store") or "", int(r.get("order_id") or 0)))
        except (TypeError, ValueError):
            m = None
        if m and m.get("outcome") in OUTCOMES:
            r["resolved"] = {"outcome": m["outcome"], "label": OUTCOMES[m["outcome"]], "by": "team",
                             "who": m.get("outcome_by"), "at": m.get("outcome_at"), "detail": ""}
        elif r["manual"] and r["manual"]["status"] == "lost":
            r["resolved"] = {"outcome": "lost", "label": "Lost", "by": "team", "who": None, "at": r["manual"].get("at"),
                             "detail": "Team mark on the parcel."}
        else:
            o = carrier_outcome(r)
            if o:
                r["resolved"] = {"outcome": o, "label": OUTCOMES[o], "by": "carrier", "who": r.get("carrier_name") or None,
                                 "at": iso(r["lastScan"]), "detail": r.get("last_scan_text") or r.get("raw_status") or ""}


def build(brand: str | None, now: datetime | None = None, snap: Snapshot | None = None) -> Dataset:
    stores = brand_stores(brand)
    snap = snap or snapshot()
    now = now or datetime.now(UTC)
    source = amazon_mcf.overlay([s for s in snap.rows if s.get("store") in stores], snap.mcf)
    everything = [e for e in (_enrich(s, now) for s in source) if e]
    marks = _marks(stores)
    _mark_reshipped(everything, snap)
    _mark_resolved(everything, marks)
    rows = [r for r in everything if not r["excluded"] and not r.get("reshipped") and not r.get("resolved")]
    reshipped = [r for r in everything if not r["excluded"] and r.get("reshipped") and not r.get("resolved")]
    resolved = [r for r in everything if not r["excluded"] and r.get("resolved")]
    return Dataset(rows, everything, now, brand or "all", snap, marks, reshipped, resolved)


def _digits(name: str) -> str:
    return "".join(ch for ch in (name or "") if ch.isdigit())


def _mark_reshipped(rows: list[dict[str, Any]], snap: Snapshot) -> None:
    """Flag a parcel (or a not-dispatched order) that never arrived but was sent again, so it leaves the delay figures.
    Three signals, strongest first:
      1. a replacement order says "replacement for #NNNN" (same store): every undelivered parcel of #NNNN placed
         before the replacement;
      2. a later parcel of the same order carries the same Shopify items;
      3. the order's own note says reshipped / resent and a later parcel exists: the earlier undelivered ones."""
    by_order: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by_order.setdefault((r.get("store") or "", _digits(r["order_number"])), []).append(r)

    def flag(r: dict[str, Any], how: str, detail: str, new: dict[str, Any] | None = None) -> None:
        if r["cat"] == "delivered" or r.get("reshipped"):
            return
        r["reshipped"] = {"how": how, "detail": detail,
                          "newOrder": (new or {}).get("order"), "newTracking": (new or {}).get("tracking"),
                          "newCarrier": (new or {}).get("carrier"), "newStatus": (new or {}).get("status"),
                          "newAt": (new or {}).get("at")}

    for rp in snap.replacements or []:
        placed = ts(rp.get("placed_at"))
        new_rows = by_order.get((rp.get("store") or "", _digits(rp.get("name") or "")), [])
        best = next((x for x in sorted(new_rows, key=lambda x: RANK.get(x["cat"], 9), reverse=True)), None)
        for ref in rp["refs"]:
            for r in by_order.get((rp.get("store") or "", ref), []):
                if (r["order_number"] == rp.get("name") or (placed and r["created"] and r["created"] > placed)
                        or (placed and r.get("shipped") and r["shipped"] > placed)):   # sent after the replacement: not replaced by it
                    continue
                flag(r, "replacement_order", f"Replacement order {rp.get('name')} was placed"
                     f"{' on ' + placed.date().isoformat() if placed else ''}.",
                     {"order": rp.get("name"), "tracking": (best or {}).get("tracking_number"), "carrier": (best or {}).get("carrier_name"),
                      "status": (best or {}).get("cat"), "at": rp.get("placed_at")})

    for r in rows:   # 4. a second Amazon MCF order was sent for the same Shopify order
        sup = r.get("_mcf_superseded")
        if sup:
            flag(r, "second_amazon_order", f"A second Amazon MCF order ({sup.get('ref')}) was sent"
                 f"{' on ' + str(sup['at'])[:10] if sup.get('at') else ''}.",
                 {"order": sup.get("order"), "tracking": sup.get("tracking"), "carrier": sup.get("carrier"), "status": None,
                  "at": sup.get("at")})

    items = snap.items or {}
    for parcels in by_order.values():
        sent = sorted((r for r in parcels if r["row_kind"] in ("tracking", "shipment", "amazon") and r["shipped"]),
                      key=lambda r: r["shipped"])
        for i, old in enumerate(sent):
            later = [n for n in sent[i + 1:] if (n["shipped"] - old["shipped"]).total_seconds() >= DAY
                     and n.get("shipment_id") != old.get("shipment_id")]
            if not later or old["cat"] == "delivered":
                continue
            mine = items.get(old.get("shipment_id") or "", set())
            same = [n for n in later if mine and mine & items.get(n.get("shipment_id") or "", set())]
            if same:
                n = same[-1]
                flag(old, "sent_again", f"The same items were sent again on {n['shipped'].date().isoformat()}.",
                     {"order": n["order_number"], "tracking": n["tracking_number"], "carrier": n["carrier_name"], "status": n["cat"],
                      "at": iso(n["shipped"])})
            elif int(old.get("order_id") or 0) in (snap.reship_notes or set()):
                n = later[-1]
                flag(old, "note_says_reshipped", "The order note says it was reshipped, and a later parcel was sent.",
                     {"order": n["order_number"], "tracking": n["tracking_number"], "carrier": n["carrier_name"], "status": n["cat"],
                      "at": iso(n["shipped"])})


def flagged(ds: Dataset, r: dict[str, Any]) -> bool:
    m = ds.marks.get((r.get("store") or "", int(r.get("order_id") or 0)))
    return bool(m and m.get("flagged"))


# ------------------------------------------------------------------------------------------------ envelope / source
def freshness(snap: Snapshot, now: datetime) -> dict[str, Any]:
    """From ops.feed_freshness: the merge run (source shopify, kind import) and each store's direct Shopify read."""
    merge = [f for f in snap.feeds if f.get("source") == "shopify" and f.get("kind") == "import"]
    polls = [f for f in snap.feeds if f.get("source") == "shopify" and f.get("kind") == "poll"]
    last_ok = max((ts(f.get("last_ok_at")) for f in merge if f.get("last_ok_at")), default=None)
    out: dict[str, Any] = {"lastChecked": iso(last_ok), "staleAfterHours": STALE_HOURS, "state": "fresh", "message": "",
                           "stores": [{"store": f.get("store"), "lastOkAt": f.get("last_ok_at"),
                                       "status": f.get("last_status"), "error": (f.get("last_error") or "")[:200]}
                                      for f in polls]}
    if not snap.feeds:
        out.update(state="unknown", message="The refresh history could not be read, so freshness cannot be confirmed.")
        return out
    failed = [f for f in [*merge, *polls] if f.get("last_status") == "failed"]
    age = (now - last_ok).total_seconds() / 3600 if last_ok else None
    if age is None:
        out.update(state="no_runs", message="No refresh has finished yet.")
    elif age > STALE_HOURS:
        out.update(state="stale", message=f"No successful refresh in the last {STALE_HOURS} hours. These figures may be out of date.")
    elif failed:
        f = failed[0]
        who = f.get("store") or "the merge"
        out.update(state="failed", message=f"The last refresh for {who} failed: {(f.get('last_error') or 'no reason recorded')[:160]}. Showing the last saved data.")
    return out


def amazon_state(snap: Snapshot) -> dict[str, Any]:
    """The Amazon MCF data in Supabase (how much, where from, when Amazon was last checked) and the daily copy of the
    MCF sheet (last copy, its result, why it failed, the next one)."""
    run = next((f for f in snap.feeds if f.get("source") == "amazon" and f.get("kind") == "import"), None)
    h, m = mcf_sync.sync_time()
    sync = {"schedule": f"Daily at {h:02d}:{m:02d} IST", "lastOkAt": (run or {}).get("last_ok_at"),
            "lastAttemptAt": (run or {}).get("last_attempt_at"), "lastStatus": (run or {}).get("last_status"),
            "lastError": ((run or {}).get("last_error") or "")[:300] or None,
            "nextAt": iso(mcf_sync.next_run(datetime.now(UTC), ts((run or {}).get("last_ok_at"))))}
    failed = sync["lastStatus"] == "failed"
    out = {"sync": sync, "problem": sync["lastError"] if failed else None,
           "serviceAccount": service_account_email() if failed and "shar" in (sync["lastError"] or "").lower() else None}
    if not snap.mcf:
        return {"loaded": False, "source": None, "orders": 0, "packages": 0, "delivered": 0, "lastLoaded": None, **out}
    sources = {p.get("_source") for p in snap.mcf}
    return {"loaded": True, "source": "sheet" if sources == {"sheet"} else "amazon_api" if sources == {"amazon_api"} else "mixed",
            "orders": len({p.get("sfo_id") for p in snap.mcf}),
            "packages": sum(1 for p in snap.mcf if p.get("package_number")),
            "delivered": sum(1 for p in snap.mcf if (p.get("tracking_status") or "").upper() == "DELIVERED"),
            "lastLoaded": max((p.get("fetched_at") or "" for p in snap.mcf), default=None) or None, **out}


def envelope(ds: Dataset, **payload: Any) -> dict[str, Any]:
    return {"brand": ds.brand, "scope": ds.brand,
            "source": {"state": "ok", "reason": "", "asOf": iso(ds.snap.loaded_at), "parts": {},
                       "freshness": freshness(ds.snap, ds.now), "amazonMcf": amazon_state(ds.snap)},
            "notConfigured": [], **payload}


# ------------------------------------------------------------------------------------------------ reports
def value_at_risk(ds: Dataset) -> dict[str, Any]:
    orders: dict[str, tuple[float, str]] = {}
    for r in ds.rows:
        if r["cat"] == "red" and r.get("total") is not None and r["order_number"] not in orders:
            orders[r["order_number"]] = (float(r["total"]), r.get("currency") or "")
    if not orders:
        return {"available": True, "orders": 0, "total": None, "currency": ""}
    currencies = {c for _, c in orders.values() if c}
    mixed = len(currencies) > 1
    return {"available": True, "orders": len(orders),
            "total": None if mixed else round(sum(v for v, _ in orders.values()), 2),
            "currency": next(iter(currencies), "USD"),
            "note": "Orders are in more than one currency, so no total is shown." if mixed else ""}


def mcf_report(ds: Dataset) -> dict[str, Any]:
    seen: set[str] = set()
    rows = []
    for r in ds.rows:
        o = r["order_number"]
        if o in seen or not r.get("note_done"):
            continue
        seen.add(o)
        if (r.get("fulfillment_status") or "").upper() == "FULFILLED":
            continue
        age = whole_days(r["created"], ds.now)
        level = next((lv for d, lv in MCF_LEVELS if age is not None and age >= d), None)
        if level:
            rows.append({"order": o, "age": age, "status": (r.get("fulfillment_status") or "NOT FULFILLED").upper(),
                         "level": level, "brand": r["brand"], "amazon": r.get("amazon_status"), "shopifyUrl": shopify_url(r),
                         "amazonTracking": r.get("amazon_tracking")})
    rows.sort(key=lambda x: -(x["age"] or 0))
    return {"available": True, "rows": rows, "counts": {lv: sum(1 for x in rows if x["level"] == lv) for _, lv in MCF_LEVELS},
            "amazonKnown": ds.snap.amazon,
            "withAmazonRecord": sum(1 for x in rows if x["amazon"]),
            "rule": "DONE in the order note is the team's note that the shipping team has handled the order. Shopify still "
                    "shows these as not fulfilled 5+ days after the order, so someone must check how it was sent and mark it "
                    "fulfilled with its tracking number. The Amazon column is the hub's latest Amazon (MCF) status, where one exists."}


def verify_report(ds: Dataset) -> dict[str, Any]:
    group = [r for r in ds.rows if r["unconfirmed"]]
    # the team's results include parcels a "lost" mark has moved to Resolved
    st = Counter((r["manual"] or {}).get("status", "") for r in group + [x for x in ds.resolved or [] if x["unconfirmed"] and x["manual"]])
    return {"total": len(group), "missingTracking": sum(1 for r in group if r["missingTracking"]),
            "team": {"delivered": st["delivered"], "lost": st["lost"], "failed": st["failed"],
                     "inTransit": st["in_transit"], "notChecked": st[""]}, "teamReason": ""}


def exception_rows(ds: Dataset) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(r: dict[str, Any], kind: str, detail: str) -> None:
        t = EXC_TYPES[kind]
        out.append({"order": r["order_number"], "key": r["key"], "type": kind, "label": t["label"], "severity": t["severity"],
                    "detail": detail, "carrier": r["carrier_name"] or "Unknown",
                    "tracking": "" if r["missingTracking"] else r["tracking_number"], "days": r["days"], "brand": r["brand"],
                    "shopifyUrl": shopify_url(r)})

    dup = Counter(r["tracking_number"] for r in ds.active if r["tracking_number"])
    for r in ds.rows:
        if r["exc"]:
            add(r, "carrier_exception", f"{r['exc'].replace('_', ' ')}{': ' + r['last_scan_text'] if r.get('last_scan_text') else ''}")
    for r in ds.active:
        if r["row_kind"] == "amazon" and r.get("amazon_extra"):
            add(r, "amazon_tracking_missing", f"Amazon (MCF) sent a parcel"
                f"{' (tracking ' + r['tracking_number'] + ')' if r['tracking_number'] else ''} that is not on the Shopify order, "
                f"which lists {', '.join(r['amazon_extra'])}. Check whether the order was split or sent twice, and add the "
                f"Amazon tracking number to the Shopify order.")
        elif r["row_kind"] == "amazon" and r["shipped"]:
            add(r, "amazon_not_in_shopify", f"Amazon shipped it {r['days'] or 0} days ago"
                f"{' (tracking ' + r['tracking_number'] + ')' if r['tracking_number'] else ''}; Shopify still shows the order unfulfilled. Mark it fulfilled in Shopify.")
        if r["row_kind"] == "shipment":
            add(r, "missing_tracking", f"Dispatched {r['days'] or 0} days ago with no tracking number. Add it in Shopify.")
        if r["noMove"]:
            add(r, "stuck", f"No carrier scan for {r['scanAge']} days (last: {r.get('last_scan_text') or 'no description'}).")
        if (r["stage"] == "dispatched" and not r["unconfirmed"] and r["expected"] and not r["noMove"] and not r["exc"]
                and (ds.now - r["expected"]).total_seconds() >= DAY):
            late = int((ds.now - r["expected"]).total_seconds() // DAY)
            add(r, "overdue", f"Promised {r['expected'].date().isoformat()}, now {late} day(s) late.")
        if re.match(r"^\s*delivered", r.get("last_scan_text") or "", re.I):
            add(r, "delivered_not_marked", f"Last scan says \"{r['last_scan_text'][:80]}\" but the parcel is not marked delivered.")
        if r["tracking_number"] and dup[r["tracking_number"]] > 1:
            add(r, "duplicate_tracking", f"Tracking number {r['tracking_number']} is used on {dup[r['tracking_number']]} parcels.")
    sev = {"high": 0, "medium": 1}
    out.sort(key=lambda x: (sev[x["severity"]], -(x["days"] or 0), x["order"]))
    return out


def checks(ds: Dataset) -> dict[str, Any]:
    mcf, ver, rows = mcf_report(ds), verify_report(ds), exception_rows(ds)
    return {"mcf": mcf, "verify": ver, "reshipped": reshipped_report(ds),
            "counts": {"mcf": mcf["counts"], "toVerify": ver["total"], "missingTracking": ver["missingTracking"]},
            "exceptions": {"total": len(rows), "counts": {k: sum(1 for r in rows if r["type"] == k) for k in EXC_TYPES},
                           "types": [{"key": k, **v} for k, v in EXC_TYPES.items()], "rows": rows}}


def kpis(ds: Dataset) -> list[dict[str, Any]]:
    active = ds.active
    counts = Counter(r["cat"] for r in active)
    values = {"": len(active), "exception": sum(1 for r in ds.rows if r["exc"]), "nomove": sum(1 for r in ds.rows if r["noMove"]),
              "reshipped": len(ds.reshipped or [])}
    spec = (("", "Total active shipments", "neutral"), ("on_track", "On track (0-3 days)", "good"),
            ("grey", "Grey 2-3 days", "muted"), ("yellow", "Yellow 4-5 days", "warn"), ("orange", "Orange 6-8 days", "orange"),
            ("red", "Red 9+ days", "bad"), ("unconfirmed", "Carrier unconfirmed (no carrier updates)", "info"),
            ("exception", "Carrier exceptions", "bad"), ("nomove", f"No movement ({NO_MOVE_DAYS}+ days)", "orange"),
            ("reshipped", "Reshipped, old parcel still open", "info"))
    return [{"key": k, "label": label, "value": values[k] if k in values else counts.get(k, 0), "tone": tone}
            for k, label, tone in spec]


RESHIP_HOW = {"replacement_order": "Replacement order", "sent_again": "Same items sent again",
              "note_says_reshipped": "Note says reshipped", "second_amazon_order": "Second Amazon order"}


def reshipped_report(ds: Dataset) -> dict[str, Any]:
    rows = []
    for r in sorted(ds.reshipped or [], key=lambda r: -(r["days"] or 0)):
        rs = r["reshipped"]
        rows.append({"order": r["order_number"], "key": r["key"], "brand": r["brand"], "carrier": r["carrier_name"] or "—", "shopifyUrl": shopify_url(r),
                     "tracking": "" if r["missingTracking"] else r["tracking_number"], "oldCat": r["agingCat"],
                     "oldStatus": r["normalized_tracking_status"] or ("not dispatched" if r["stage"] == "pre_dispatch" else ""),
                     "lastScan": r.get("last_scan_text") or "", "days": r["days"], "stage": r["stage"],
                     "how": rs["how"], "howLabel": RESHIP_HOW.get(rs["how"], rs["how"]), "detail": rs["detail"],
                     "newOrder": rs.get("newOrder"), "newTracking": rs.get("newTracking"), "newCarrier": rs.get("newCarrier"),
                     "newStatus": rs.get("newStatus"), "newAt": rs.get("newAt"),
                     "action": "Close the old fulfilment in Shopify (or cancel the Amazon MCF order) so it stops showing as open."})
    return {"total": len(rows), "rows": rows,
            "counts": {k: sum(1 for x in rows if x["how"] == k) for k in RESHIP_HOW},
            "rule": "A parcel that never arrived but was sent again: a replacement order names it, a later parcel of the same "
                    "order carries the same items, or the order note says it was reshipped. These are left out of every "
                    "delay figure."}


def summary(ds: Dataset) -> dict[str, Any]:
    active = ds.active
    critical = sum(1 for r in active if r["cat"] == "red")
    c = checks(ds)
    return {
        "kpis": kpis(ds), "activeTotal": len(active), "critical": critical,
        "delivered": sum(1 for r in ds.rows if r["cat"] == "delivered"),
        "stage": {"preDispatch": sum(1 for r in active if r["stage"] == "pre_dispatch"),
                  "dispatched": sum(1 for r in active if r["stage"] == "dispatched"),
                  "delivered": sum(1 for r in ds.rows if r["cat"] == "delivered")},
        "banner": f"CRITICAL: {critical} shipment(s) are {THRESH['red']}+ days in stage. Escalate today." if critical else "",
        "valueAtRisk": value_at_risk(ds), "checks": c["counts"], "exceptions": c["exceptions"]["total"],
        "thresholds": {**THRESH, "noMove": NO_MOVE_DAYS},
        "totals": {"shipments": len(ds.everything), "afterExclusions": len(ds.rows)},
        "deliveredWindowDays": DELIVERED_KEEP_DAYS,
    }


def carriers_report(ds: Dataset) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {}
    for r in ds.rows:
        c = by.setdefault(r["carrier_name"] or "Unknown", {"n": 0, "crit": 0, "stuck": 0, "exc": 0, "days": [], "cats": Counter()})
        if r["cat"] != "delivered":
            c["n"] += 1
            c["cats"][r["cat"]] += 1
            if r["days"] is not None:
                c["days"].append(r["days"])
            if r["noMove"]:
                c["stuck"] += 1
        if r["cat"] == "red":
            c["crit"] += 1
        if r["exc"]:
            c["exc"] += 1
    scored = []
    for name, c in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        if not c["n"]:
            continue
        pct = round(c["crit"] / c["n"] * 100)
        scored.append({"carrier": name, "active": c["n"], "critical": c["crit"], "criticalPct": pct, "stuck": c["stuck"],
                       "exceptions": c["exc"], "avgDays": round(sum(c["days"]) / len(c["days"])) if c["days"] else None,
                       "health": "bad" if pct > 50 else "warn" if pct > 20 else "ok",
                       "healthLabel": "Needs action" if pct > 50 else "Watch" if pct > 20 else "Healthy",
                       "cats": {k: c["cats"].get(k, 0) for k in AGING_KEYS}})
    return {"scorecard": scored, "heatmap": scored[:8],
            "categories": [{"key": k, "label": AGING_LABELS[k]} for k in AGING_KEYS]}


def _week(d: datetime) -> str:
    x = d.astimezone(UTC).date()
    return (x - timedelta(days=x.weekday())).isoformat()


def delivery_report(ds: Dataset, period: int) -> dict[str, Any]:
    """Parcels delivered in the last `period` days, dispatch to delivery. On time = by the end of the promised day;
    parcels without a promised date are left out of the on-time share (counted in delivered and average days)."""
    since = ds.now - timedelta(days=period)
    done = [r for r in ds.rows if r["cat"] == "delivered" and r["deliveredAt"] and r["deliveredAt"] >= since and r["shipped"]]

    def days(r: dict[str, Any]) -> float:
        return max(0.0, (r["deliveredAt"] - r["shipped"]).total_seconds() / DAY)

    def pct(lst: list[dict[str, Any]]) -> int | None:
        promised = [r for r in lst if r["expected"]]
        return round(sum(1 for r in promised if r["deliveredAt"] <= r["expected"]) / len(promised) * 100) if promised else None

    def avg(lst: list[dict[str, Any]]) -> float | None:
        return round(sum(days(r) for r in lst) / len(lst), 1) if lst else None

    def group(key: Any) -> list[dict[str, Any]]:
        m: dict[str, list[dict[str, Any]]] = {}
        for r in done:
            m.setdefault(key(r), []).append(r)
        return sorted(({"name": k, "delivered": len(v), "onTimePct": pct(v), "avgDays": avg(v)} for k, v in m.items()),
                      key=lambda g: -g["delivered"])

    buckets = (("1-2 days", 0, 3), ("3-4 days", 3, 5), ("5-6 days", 5, 7), ("7-8 days", 7, 9), ("9+ days", 9, 10**9))
    weeks: dict[str, list[dict[str, Any]]] = {}
    for r in done:
        weeks.setdefault(_week(r["deliveredAt"]), []).append(r)
    return {
        "period": period, "delivered": len(done), "onTimePct": pct(done), "avgDays": avg(done),
        "withPromisedDate": sum(1 for r in done if r["expected"]),
        "distribution": [{"key": lb, "label": lb, "value": sum(1 for r in done if lo <= days(r) < hi)} for lb, lo, hi in buckets],
        "byCarrier": [{"carrier": g["name"], "delivered": g["delivered"], "onTimePct": g["onTimePct"], "avgDays": g["avgDays"]}
                      for g in group(lambda r: r["carrier_name"] or "Unknown")],
        "byRegion": [{"region": g["name"], "delivered": g["delivered"], "onTimePct": g["onTimePct"], "avgDays": g["avgDays"]}
                     for g in group(lambda r: r.get("ship_state") or "Unknown")[:8]],
        "trend": [{"week": w, "onTimePct": pct(v), "delivered": len(v)} for w, v in sorted(weeks.items())],
    }


def analytics(ds: Dataset, period: int) -> dict[str, Any]:
    active = ds.active
    crit = sum(1 for r in active if r["cat"] == "red")
    stuck = sum(1 for r in active if r["noMove"])
    day_list = [r["days"] for r in active if r["days"] is not None]
    count = Counter(r["cat"] for r in active)
    weeks = Counter(_week(r["created"]) for r in active if r["created"])
    week_rows = sorted(weeks.items())[-12:]
    cr = carriers_report(ds)
    car = cr["scorecard"][:8]
    dispatch: Counter[str] = Counter()
    dispatch_crit: Counter[str] = Counter()
    for r in active:
        d = WEEKDAYS[r["shipped"].astimezone(IST).weekday()] if r["shipped"] else "No date"
        dispatch[d] += 1
        if r["cat"] == "red":
            dispatch_crit[d] += 1
    labels = [d for d in WEEKDAYS if dispatch[d]] + (["No date"] if dispatch["No date"] else [])
    exc = sum(1 for r in ds.rows if r["exc"])
    tips: list[str] = []
    if crit:
        tips.append(f"{crit} active shipments are {THRESH['red']}+ days in stage. Escalate these first (filter: Critical).")
    worst = max(car, key=lambda c: c["critical"], default=None)
    if worst and worst["critical"]:
        tips.append(f"{worst['carrier']} has the most critical shipments ({worst['critical']}). Check them with this carrier first.")
    if stuck:
        tips.append(f"{stuck} shipments have had no carrier scan for {NO_MOVE_DAYS}+ days. These may be stuck or lost.")
    if exc:
        tips.append(f"{exc} carrier exception(s) need a decision (failed delivery, delay or return).")
    unconf = count["unconfirmed"]
    if unconf:
        tips.append(f"{unconf} parcels have no carrier update at all (Amazon, or tracking Shopify never received). Check them by hand (Checks tab).")
    return {
        "kpis": {"active": len(active), "critical": crit, "criticalPct": round(crit / len(active) * 100) if active else 0,
                 "onTrackPct": round(count["on_track"] / len(active) * 100) if active else 0,
                 "avgDays": round(sum(day_list) / len(day_list)) if day_list else None, "stuck": stuck,
                 "carriersInUse": len({r["carrier_name"] or "Unknown" for r in active if r["stage"] != "pre_dispatch"}),
                 "valueAtRisk": value_at_risk(ds)},
        "aging": [{"key": k, "label": AGING_LABELS[k], "value": count[k]} for k in AGING_KEYS],
        "weeks": [{"week": w, "value": n} for w, n in week_rows],
        "carriers": [{"carrier": c["carrier"], "critical": c["critical"], "other": c["active"] - c["critical"]} for c in car],
        "stage": [{"label": "Not dispatched", "value": sum(1 for r in active if r["stage"] == "pre_dispatch")},
                  {"label": "Dispatched (active)", "value": sum(1 for r in active if r["stage"] == "dispatched")},
                  {"label": f"Delivered (last {DELIVERED_KEEP_DAYS} days)", "value": sum(1 for r in ds.rows if r["cat"] == "delivered")}],
        "dispatchDay": [{"day": d, "critical": dispatch_crit[d], "other": dispatch[d] - dispatch_crit[d]} for d in labels],
        "insights": tips, "carriersReport": cr, "delivery": delivery_report(ds, period),
    }


# ------------------------------------------------------------------------------------------------ list
def _sort_key(sort: str) -> Any:
    def order_digits(n: str) -> int:
        d = "".join(ch for ch in n if ch.isdigit())
        return int(d) if d else 0
    return {
        "priority": lambda r: (0 if r["exc"] else 1, 0 if r["noMove"] else 1, RANK.get(r["cat"], 9), -(r["days"] or 0)),
        "stuck": lambda r: (0 if r["noMove"] else 1, -(r["scanAge"] or 0)),
        "order": lambda r: (order_digits(r["order_number"]), r["order_number"]),
        "oldest": lambda r: (-(r["days"] if r["days"] is not None else -1),),
    }[sort if sort in SORTS else "priority"]


def select_rows(ds: Dataset, q: str = "", carrier: str = "", cat: str = "", status: str = "", days: int = 0,
                sort: str = "priority") -> list[dict[str, Any]]:
    needle = q.strip().lower()
    cutoff = ds.now - timedelta(days=days) if days else None
    out = []
    source = (ds.reshipped or []) if cat == "reshipped" else (ds.resolved or []) if cat == "resolved" else ds.rows
    for r in source:
        if r["cat"] == "delivered":
            continue
        if cutoff and (not r["created"] or r["created"] < cutoff):
            continue
        if cat in ("reshipped", "resolved"):
            pass                                     # the whole list, filtered only by the fields below
        elif cat == "nomove":
            if not r["noMove"]:
                continue
        elif cat == "noscan":
            if r["lastScan"] or r["stage"] == "pre_dispatch":
                continue
        elif cat == "exception":
            if not r["exc"]:
                continue
        elif cat == "flagged":
            if not flagged(ds, r):
                continue
        elif cat and r["cat"] != cat:
            continue
        if carrier and r["carrier_name"] != carrier:
            continue
        if status and r["normalized_tracking_status"] != status:
            continue
        if needle and needle not in r["order_number"].lower() and needle not in r["tracking_number"].lower():
            continue
        out.append(r)
    out.sort(key=_sort_key(sort))
    return out


def shopify_url(r: dict[str, Any]) -> str:
    """The order's page in Shopify admin (admin.shopify.com/store/<store>/orders/<id>), or "" when the store or the
    Shopify order id is unknown (an Amazon-only row, an imported row without an id)."""
    from ..seo.config import config
    from .shopify_source import STORE_BRAND
    try:
        oid = int(r.get("order_id") or 0)
    except (TypeError, ValueError):
        return ""
    b = config.brands.get(STORE_BRAND.get(r.get("store") or "", ""))
    shop = (b.shop_domain if b else "") or ""
    handle = shop[:-len(".myshopify.com")] if shop.endswith(".myshopify.com") else ""
    if oid <= 0 or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", handle):
        return ""
    return f"https://admin.shopify.com/store/{handle}/orders/{oid}"


def public_row(ds: Dataset, r: dict[str, Any], packages: dict[str, int]) -> dict[str, Any]:
    """What the browser receives for one parcel. No note text, no customer data beyond city and state."""
    return {
        "key": r["key"], "order": r["order_number"], "tracking": r["tracking_number"], "carrier": r["carrier_name"],
        "cat": ("resolved" if r.get("resolved") else "reshipped" if r.get("reshipped") and r["cat"] != "delivered" else r["cat"]),
        "agingCat": r["agingCat"],
        "label": f"Resolved: {r['resolved']['label']}" if r.get("resolved") else LABELS.get(r["cat"], r["cat"]), "days": r["days"],
        "stage": r["stage"], "exception": r["exc"], "noMove": r["noMove"], "scanAge": r["scanAge"],
        "status": r["normalized_tracking_status"], "orderCreatedAt": iso(r["created"]), "dispatchedAt": iso(r["shipped"]),
        "lastScanAt": iso(r["lastScan"]), "lastScan": r.get("last_scan_text") or "", "expectedAt": r.get("eta"),
        "trackUrl": r.get("track_url") or "", "shopifyUrl": shopify_url(r), "manual": r["manual"],
        "packages": packages.get(r["order_number"], 1), "missingTracking": r["missingTracking"],
        "unconfirmed": r["unconfirmed"], "flagged": flagged(ds, r), "brand": r["brand"],
        "city": r.get("ship_city"), "state": r.get("ship_state"), "trackingId": r.get("tracking_id"),
        "kind": r.get("kind"), "rowKind": r["row_kind"],
        "amazonStatus": r.get("amazon_status"), "amazonAt": r.get("amazon_at"), "amazonRef": r.get("amazon_ref"),
        "amazonTracking": r.get("amazon_tracking"),
        "reshipped": r.get("reshipped"), "resolved": r.get("resolved"),
    }


def _packages(ds: Dataset) -> dict[str, int]:
    p: dict[str, int] = {}
    for r in ds.rows:
        if r["row_kind"] != "order":
            p[r["order_number"]] = p.get(r["order_number"], 0) + 1
    return p


def list_rows(ds: Dataset, page: int = 0, size: int = 25, **filters: Any) -> dict[str, Any]:
    out = select_rows(ds, **filters)
    size = max(1, min(size, 200))
    pages = max(1, -(-len(out) // size))
    page = max(0, min(page, pages - 1))
    pk = _packages(ds)
    return {"total": len(out), "page": page, "size": size, "pages": pages,
            "rows": [public_row(ds, r, pk) for r in out[page * size:(page + 1) * size]],
            "facets": {"carriers": sorted({r["carrier_name"] for r in ds.rows if r["carrier_name"]}),
                       "statuses": sorted({r["normalized_tracking_status"] for r in ds.rows if r["normalized_tracking_status"]})}}


# ------------------------------------------------------------------------------------------------ order detail
def _find(ds: Dataset, order: str) -> list[dict[str, Any]]:
    return [r for r in ds.everything if r["order_number"] == order]


def _events(tracking_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not tracking_ids:
        return {}
    rows = client().select("tracking_scans", [("select", "tracking_id,scanned_at,status,raw_status,message,city,province,country"),
                                              ("tracking_id", f"in.({','.join(tracking_ids)})"),
                                              ("order", "scanned_at.asc")], limit=1000).rows
    out: dict[str, list[dict[str, Any]]] = {}
    for e in rows:
        place = ", ".join(x for x in (e.get("city"), e.get("province"), e.get("country")) if x)
        desc = e.get("message") or (e.get("raw_status") or e.get("status") or "").replace("_", " ").capitalize()
        out.setdefault(e["tracking_id"], []).append({"at": e.get("scanned_at"), "status": e.get("status"),
                                                     "description": desc or "Carrier update", "location": place})
    return out


def _amazon_events(r: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in r.get("amazon_events") or []:
        place = ", ".join(x for x in (e.get("city"), e.get("state"), e.get("country")) if x)
        delivered = "deliver" in (e.get("text") or "").lower()
        out.append({"at": e.get("at"), "status": "delivered" if delivered else "in_transit",
                    "description": f"Amazon: {e.get('text') or e.get('code') or 'update'}", "location": place})
    return out


def annotation(store: str, order_id: int) -> dict[str, Any]:
    m = get("SELECT * FROM shipping_order_marks WHERE store = ? AND order_id = ?", store, order_id) or {}
    notes = all_rows("SELECT at, by, text FROM shipping_order_notes WHERE store = ? AND order_id = ? ORDER BY id DESC LIMIT 50",
                     store, order_id)
    return {"reviewedAt": m.get("reviewed_at"), "reviewedBy": m.get("reviewed_by"), "flagged": bool(m.get("flagged")),
            "flaggedAt": m.get("flagged_at"), "notes": notes,
            "outcome": m.get("outcome") if m.get("outcome") in OUTCOMES else None,
            "outcomeLabel": OUTCOMES.get(m.get("outcome") or ""), "outcomeAt": m.get("outcome_at"), "outcomeBy": m.get("outcome_by")}


def order_detail(ds: Dataset, order: str) -> dict[str, Any] | None:
    pkgs = _find(ds, order)
    if not pkgs:
        return None
    first = pkgs[0]
    parcels = [p for p in pkgs if p["row_kind"] != "order"] or pkgs
    ev = _events([p["tracking_id"] for p in parcels if p.get("tracking_id")])
    counts = {order: len(parcels)}

    def action(r: dict[str, Any]) -> str:
        if r["cat"] == "delivered":
            return ACTIONS["delivered"]
        if r.get("resolved"):
            rs = r["resolved"]
            who = f"the team{' (' + rs['who'] + ')' if rs.get('who') else ''}" if rs["by"] == "team" else f"the carrier ({rs.get('detail') or 'last update'})"
            return f"Resolved as {rs['label'].lower()} by {who}, so it is out of Critical and the delay figures. Nothing more to do here."
        if r["exc"]:
            return f"Carrier exception ({r['exc'].replace('_', ' ')}): review the reason and decide the next step."
        if r["row_kind"] == "amazon":
            if r["shipped"]:
                return ("Amazon shipped this, but Shopify still shows the order unfulfilled. Mark it fulfilled in Shopify"
                        + (f" with tracking {r['tracking_number']}" if r["tracking_number"] else "") + ", then check delivery on the carrier page.")
            return "Amazon has the request but has not shipped it yet. Check the order in Amazon Seller Central."
        if r["missingTracking"] and r["row_kind"] == "shipment":
            return "Add the tracking number in Shopify."
        if r.get("hubFailure"):
            return ("Shopify's only word for this older order is \"failed delivery\", with no carrier history (DHL often adds "
                    "a stray failure after delivering). Check the parcel on the carrier page, then record a team mark.")
        if r["unconfirmed"]:
            return "Sent through Amazon, which does not report delivery. Check the parcel on the carrier page, then record a team mark."
        if r["stage"] == "pre_dispatch":
            return "Not dispatched yet. " + ACTIONS.get(r["agingCat"], "Review manually.")
        return ACTIONS.get(r["agingCat"], "Review manually.")

    return {
        "order": order, "excluded": first["excluded"], "brand": first["brand"], "shopifyUrl": shopify_url(first),
        "destination": {"city": first.get("ship_city") or "—", "state": first.get("ship_state") or "—"}
        if first.get("ship_city") or first.get("ship_state") else None,
        "items": [],
        "packages": [{**public_row(ds, r, counts), "action": action(r), "location": r.get("last_scan_place") or "",
                      "source": r.get("source") or "", "checkedAt": r.get("last_check_ok_at"),
                      "scanDescription": r.get("last_scan_text") or "",
                      "events": ev.get(r.get("tracking_id") or "", []) or _amazon_events(r),
                      "promisedAt": r.get("eta"), "deliveredAt": iso(r["deliveredAt"]), "rowKind": r["row_kind"]}
                     for r in parcels],
        "check": {"fulfillment": (first.get("fulfillment_status") or "").upper(),
                  "financial": (first.get("financial_status") or "").upper(), "cancelled": bool(first.get("cancelled_at")),
                  "notesSayDone": bool(first.get("note_done")), "createdAt": iso(first["created"]),
                  "total": float(first["total"]) if first.get("total") is not None else None,
                  "currency": first.get("currency") or "",
                  "amazon": first.get("amazon_status"), "amazonAt": first.get("amazon_at"),
                  "amazonRef": first.get("amazon_ref"), "amazonKnown": ds.snap.amazon},
        "checkAvailable": True,
        "annotation": annotation(first["store"], int(first["order_id"])),
    }


def annotate(ds: Dataset, order: str, action: str, text: str, by: str) -> dict[str, Any]:
    pkgs = _find(ds, order)
    if not pkgs:
        raise HttpError(404, "No shipment found for that order.", "not_found")
    store, oid = pkgs[0]["store"], int(pkgs[0]["order_id"])
    at = db_now()
    run("INSERT OR IGNORE INTO shipping_order_marks (store, order_id) VALUES (?, ?)", store, oid)
    if action == "check":
        run("UPDATE shipping_order_marks SET reviewed_at = ?, reviewed_by = ? WHERE store = ? AND order_id = ?", at, by, store, oid)
    elif action == "uncheck":
        run("UPDATE shipping_order_marks SET reviewed_at = NULL, reviewed_by = NULL WHERE store = ? AND order_id = ?", store, oid)
    elif action == "flag":
        run("UPDATE shipping_order_marks SET flagged = 1, flagged_at = ?, flagged_by = ? WHERE store = ? AND order_id = ?", at, by, store, oid)
    elif action == "unflag":
        run("UPDATE shipping_order_marks SET flagged = 0, flagged_at = NULL, flagged_by = NULL WHERE store = ? AND order_id = ?", store, oid)
    elif action == "note":
        t = (text or "").strip()
        if not t:
            raise HttpError(400, "Write a note first.", "bad_request")
        run("INSERT INTO shipping_order_notes (store, order_id, at, by, text) VALUES (?,?,?,?,?)", store, oid, at, by, t[:500])
    elif action == "outcome":
        outcome = (text or "").strip().lower()
        if outcome not in OUTCOMES:
            raise HttpError(400, f"Outcome must be one of: {', '.join(OUTCOMES)}.", "bad_request")
        run("UPDATE shipping_order_marks SET outcome = ?, outcome_at = ?, outcome_by = ? WHERE store = ? AND order_id = ?",
            outcome, at, by, store, oid)
    elif action == "clear_outcome":
        run("UPDATE shipping_order_marks SET outcome = NULL, outcome_at = NULL, outcome_by = NULL WHERE store = ? AND order_id = ?",
            store, oid)
    else:
        raise HttpError(400, "Unknown action.", "bad_request")
    if action in ("outcome", "clear_outcome"):    # the outcome moves parcels between lists: rebuild them
        fresh = build(ds.brand, now=ds.now, snap=ds.snap)
        ds.rows, ds.everything, ds.marks, ds.reshipped, ds.resolved = (fresh.rows, fresh.everything, fresh.marks,
                                                                       fresh.reshipped, fresh.resolved)
    else:
        ds.marks = _marks(brand_stores(ds.brand))
    detail = order_detail(ds, order)
    assert detail is not None
    return detail


# ------------------------------------------------------------------------------------------------ CSV
def _cell(v: Any) -> str:
    if v is None:
        return ""
    text = iso(v) if isinstance(v, datetime) else str(v)
    return "'" + (text or "") if (text or "")[:1] in ("=", "+", "-", "@", "\t", "\r") else (text or "")


def to_csv(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return buf.getvalue()


def csv_shipments(rows: list[dict[str, Any]]) -> str:
    return to_csv(["brand", "order_number", "carrier_name", "tracking_number", "category", "days_in_stage", "stage", "exception",
                   "no_movement", "tracking_status", "order_created_at", "dispatched_at", "last_scan_at", "last_scan",
                   "promised_delivery", "tracking_url"],
                  [[r["brand"], r["order_number"], r["carrier_name"], r["tracking_number"], r["cat"], r["days"], r["stage"], r["exc"],
                    "yes" if r["noMove"] else "", r["normalized_tracking_status"], r["created"], r["shipped"], r["lastScan"],
                    r.get("last_scan_text"), r.get("eta"), r.get("track_url")] for r in rows])


def csv_escalation(ds: Dataset) -> tuple[str, int]:
    rows = sorted((r for r in ds.active if r["cat"] == "red" or r["noMove"] or flagged(ds, r)), key=lambda r: -(r["days"] or 0))

    def reason(r: dict[str, Any]) -> str:
        if r["cat"] == "red" and r["noMove"]:
            return "critical + stuck"
        return "critical" if r["cat"] == "red" else "stuck" if r["noMove"] else "flagged by team"
    return to_csv(["brand", "order_number", "carrier_name", "tracking_number", "days_in_stage", "stage", "reason", "last_scan_at",
                   "last_scan_description", "tracking_url"],
                  [[r["brand"], r["order_number"], r["carrier_name"], r["tracking_number"], r["days"], r["stage"], reason(r),
                    r["lastScan"], r.get("last_scan_text"), r.get("track_url")] for r in rows]), len(rows)


def csv_verify(ds: Dataset) -> tuple[str, int]:
    rows = sorted((r for r in ds.rows if r["cat"] == "unconfirmed"), key=lambda r: (not r["missingTracking"], -(r["days"] or 0)))
    return to_csv(["brand", "action", "order_number", "carrier_name", "tracking_number", "dispatched", "days_in_stage",
                   "last_scan_at", "team_status", "track_url"],
                  [[r["brand"], "ADD TRACKING NUMBER IN SHOPIFY" if r["missingTracking"] else "Check carrier page", r["order_number"],
                    r["carrier_name"], "" if r["missingTracking"] else r["tracking_number"], r["shipped"], r["days"], r["lastScan"],
                    (r["manual"] or {}).get("status", "not checked"), "" if r["missingTracking"] else r.get("track_url")]
                   for r in rows]), len(rows)


# ------------------------------------------------------------------------------------------------ import preview
def import_carriers(ds: Dataset) -> list[str]:
    return sorted({r["carrier_name"] for r in ds.everything if r["carrier_name"] and r["carrier_name"] != "Unknown carrier"})


def preview_import(ds: Dataset, text: str) -> dict[str, Any]:
    """Checks a sheet (order_number, tracking_number, carrier) against the active parcels and says what WOULD change.
    It writes nothing, anywhere."""
    if len(text.encode("utf-8", "ignore")) > IMPORT_MAX_BYTES:
        raise HttpError(413, "That sheet is too large to preview.", "too_large")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise HttpError(400, "The sheet is empty.", "bad_request")
    parsed = list(csv.reader(lines))
    header = [h.strip().lower().replace(" ", "_") for h in parsed[0]]
    try:
        io_, it, ic = header.index("order_number"), header.index("tracking_number"), header.index("carrier")
    except ValueError:
        raise HttpError(400, "The first row must have: order_number, tracking_number, carrier.", "bad_request") from None
    body = parsed[1:]
    if len(body) > IMPORT_MAX_ROWS:
        raise HttpError(400, f"At most {IMPORT_MAX_ROWS} rows can be previewed at once.", "bad_request")

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if i < len(row) else ""
    sheet = [{"line": n + 2, "order": cell(r, io_), "tracking": cell(r, it), "carrier": cell(r, ic)} for n, r in enumerate(body)]
    by_order: dict[str, list[dict[str, Any]]] = {}
    for r in ds.active:
        if r["row_kind"] != "order":
            by_order.setdefault(r["order_number"], []).append(r)
    dup = Counter((s["order"], s["tracking"]) for s in sheet if s["order"])
    allowed = {c.lower(): c for c in import_carriers(ds)}
    out = []
    for s in sheet:
        outcome, why = _check_row(s, dup, allowed, by_order)
        out.append({**s, "carrier": allowed.get(s["carrier"].lower(), s["carrier"]), "outcome": outcome, "message": why})
    counts = Counter(o["outcome"] for o in out)
    return {"previewOnly": True, "rows": out, "counts": {k: counts[k] for k in ("will_update", "skip_has_tracking", "ambiguous", "error")},
            "carriers": list(allowed.values()), "note": "Preview only. Nothing was changed in Shopify, Supabase or Flowmerce."}


def _check_row(s: dict[str, Any], dup: Counter, allowed: dict[str, str],
               by_order: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    if not s["order"]:
        return "error", "Order number is missing."
    if dup[(s["order"], s["tracking"])] > 1:
        return "error", "Duplicate row in this sheet."
    if not s["tracking"]:
        return "error", "Tracking number is missing."
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{5,39}", s["tracking"]):
        return "error", "Tracking number looks wrong (letters, digits and dashes, 6 to 40 characters)."
    if s["carrier"].lower() not in allowed:
        return "error", "Carrier must be one of: " + ", ".join(allowed.values()) + "."
    pkgs = by_order.get(s["order"])
    if not pkgs:
        return "error", "Order not found among active parcels."
    blank = [p for p in pkgs if p["missingTracking"]]
    if not blank:
        return "skip_has_tracking", "Every parcel of this order already has a tracking number."
    if len(blank) > 1:
        return "ambiguous", f"{len(blank)} parcels of this order have no tracking number. Choose one."
    return "will_update", "Would add this tracking number to the one parcel without one (preview only)."


def sample_sheet(ds: Dataset) -> str:
    blank = [r for r in ds.active if r["row_kind"] == "shipment"][:3]
    has = next((r for r in ds.active if r["tracking_number"]), None)
    carrier = (import_carriers(ds) or ["USPS"])[0]
    lines = ["order_number,tracking_number,carrier"]
    lines += [f"{r['order_number']},EXAMPLE{1000001 + i},{r['carrier_name'] or carrier}" for i, r in enumerate(blank)]
    if has:
        lines.append(f"{has['order_number']},EXAMPLE2000002,{has['carrier_name'] or carrier}")
    lines.append(f"#000000,EXAMPLE3000003,{carrier}")
    lines.append(f"{blank[0]['order_number'] if blank else '#000001'},12,{carrier}")
    return "\n".join(lines)
