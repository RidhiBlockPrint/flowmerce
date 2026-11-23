"""The Shipping page: one cached snapshot of ops.flow_board, turned into every figure the page shows.

Rules (agreed with operations on 23 Nov 2026):
  * Only DISPATCHED parcels are tracked, and only those dispatched in the last TRACK_DAYS (120) days: an open parcel
    sent longer ago is not listed (agreed 23 Nov: older history would flood Critical). Orders not sent yet (Shopify unfulfilled, or with Amazon but not shipped)
    are not shown anywhere, and neither are cancelled or refunded orders (nor cancelled Amazon MCF orders).
  * Delivered by ANY evidence (Shopify, the carrier, Amazon's MCF data or its word on the order, a last scan saying
    "Delivered", a team mark or outcome, another parcel of the order, a shared tracking number): the whole order is
    delivered and leaves every list; it only counts in the delivery figures.
  * The clock: days since the last carrier scan, or since dispatch while there is no scan yet. A scan resets it.
    On track 0-3, Yellow 4-5, Orange 6-8, Critical 9+.
  * Every active order is in exactly ONE section, the first that applies to any of its parcels:
    Tracking missing (dispatched without a tracking number) > Invalid tracking (a number that never got any carrier
    status or scan, NO_SCAN_GRACE_DAYS after dispatch) > Fix in Shopify (Amazon shipped but Shopify shows it
    unfulfilled, an Amazon parcel the Shopify order does not list, a tracking number used on two parcels) >
    Critical > Orange > Yellow > On track. All of the order's active parcels are listed in that section.
  * Outside the active sections: Reshipped (an old parcel that was sent again) and Resolved (lost, returned, refunded
    or couldn't deliver, by the team or the carrier's own words).
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
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any

from ..seo.db import all_rows, get, now as db_now, run
from ..seo.util import HttpError
from . import amazon_mcf, mcf_sync
from ..seo.integrations.google import service_account_email
from .supabase import SupabaseError, client

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))     # India has no daylight saving: a fixed offset is exact
DAY = 86400

THRESH = {"yellow": 4, "orange": 6, "red": 9}
NO_SCAN_GRACE_DAYS = 3          # a carrier's first scan normally reaches Shopify within 1-2 days of dispatch
DELIVERED_KEEP_DAYS = 100       # delivered parcels kept in the snapshot (delivery performance looks back 90 days)
TRACK_DAYS = 120                # open parcels dispatched longer ago than this are not tracked here
CACHE_SECONDS = 20 * 60        # the data changes only when a refresh runs (every 15 min); each refresh reloads it
BUILT_SECONDS = 5 * 60          # a built board (every figure of the page) is reused this long for the same snapshot
STALE_HOURS = 2                 # the refresh runs every 15 minutes; 2 hours without success is stale

BRAND_STORE = {"ridhi": "RBP", "cpc": "CPC"}
STORE_BRAND = {v: k for k, v in BRAND_STORE.items()}

# The active sections, first wins: an order is listed in the first one that applies to any of its parcels
SECTIONS = ("tracking_missing", "invalid", "checks", "red", "orange", "yellow", "on_track")
RANK = {k: i for i, k in enumerate(SECTIONS)}
LABELS = {"on_track": "On track 0-3 days", "yellow": "Yellow 4-5 days", "orange": "Orange 6-8 days",
          "red": "Critical 9+ days", "tracking_missing": "Tracking missing", "invalid": "Invalid tracking",
          "checks": "Fix in Shopify", "delivered": "Delivered"}
ACTIONS = {"on_track": "Continue monitoring.",
           "yellow": "Review if the carrier or the promised delivery date shows a problem.",
           "orange": "Prioritise for investigation.", "red": "Add to the urgent escalation list.",
           "tracking_missing": "Add the tracking number in Shopify.",
           "invalid": "The carrier has never reported anything on this number: check it on the carrier page, correct it in "
                      "Shopify if it is wrong, then record a team mark.",
           "delivered": "None. Delivered."}
# every active section; the age charts list them all, so their bars add up to the active shipments
AGING_KEYS = SECTIONS
AGING_LABELS = {"red": "Critical 9+", "orange": "Orange 6-8", "yellow": "Yellow 4-5", "on_track": "On track",
                "tracking_missing": "Tracking missing", "invalid": "Invalid tracking", "checks": "Fix in Shopify"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TEAM_STATES = ("delivered", "lost", "failed", "in_transit")
OUTCOMES = {"delivered": "Delivered", "lost": "Lost", "returned": "Returned", "refunded": "Refunded",
            "failed": "Couldn't deliver"}
TEAM_OUTCOMES = ("delivered", "lost", "returned", "refunded")       # what the team can set on a whole order
LOST_RE = re.compile(r"\bdispos(?:e|al|ed)\b|\bdestroy(?:ed)?\b|\blost\b", re.I)
RETURN_RE = re.compile(r"return(?:ed|ing)?\s+to\s+(?:the\s+)?(?:sender|shipper|seller|origin|amazon)|\brts\b", re.I)
RETURN_RAW = {"RETURNED", "RETURNING", "RETURNED_TO_SENDER", "RETURN_TO_SENDER", "UNDELIVERABLE"}
# The hand checks: every order in the Tracking missing, Invalid tracking or Fix in Shopify section, one row each
EXC_TYPES = {
    "missing_tracking": {"label": "Tracking missing", "severity": "high", "section": "tracking_missing"},
    "invalid_tracking": {"label": "Invalid tracking", "severity": "high", "section": "invalid"},
    "amazon_not_in_shopify": {"label": "Shipped by Amazon, unfulfilled in Shopify", "severity": "medium", "section": "checks"},
    "amazon_tracking_missing": {"label": "Amazon parcel not on the Shopify order", "severity": "medium", "section": "checks"},
    "duplicate_tracking": {"label": "Duplicate tracking number", "severity": "medium", "section": "checks"},
}
SORTS = ("priority", "order", "oldest")
HAND_CHECKS = ("tracking_missing", "invalid", "checks")
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


def band(days: int) -> str:
    t = THRESH
    return "red" if days >= t["red"] else "orange" if days >= t["orange"] else "yellow" if days >= t["yellow"] else "on_track"


def flow_category(dispatched: datetime | None, last_scan: datetime | None, now: datetime,
                  delivered: bool) -> tuple[str, int | None, str]:
    """(category, days on the clock, stage). The clock runs from the last carrier scan, or from dispatch while there is
    no scan yet: a scan resets it."""
    if delivered:
        return "delivered", None, "delivered"
    if dispatched is None:
        return "", None, "pre_dispatch"           # not sent yet: not tracked on this page
    since = max(dispatched, last_scan) if last_scan else dispatched
    d = whole_days(since, now) or 0
    return band(d), d, "dispatched"


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
    numbers: dict[str, set[str]] | None = None           # shipment id -> EVERY tracking number on that fulfilment


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
        items, replacements, notes, numbers = signals_f.result()
        return Snapshot(rows, feeds_f.result(), datetime.now(UTC), amazon, items, replacements, notes, mcf_f.result(),
                        numbers)


REF_RE = re.compile(r"(?:replace?ment\s+(?:for|of)|reship(?:ped)?\s+(?:for|of)|instead\s+of)\s*(?:order\s*)?#?\s*(?:RBP\s*)?(\d{3,7})", re.I)
RESHIP_RE = re.compile(r"\b(re-?ship(?:ped|ment)?|re-?sen[dt]|sent\s+again|shipped\s+again)\b", re.I)


def _reship_signals() -> tuple[dict[str, set[str]], list[dict[str, Any]], set[int], dict[str, set[str]]]:
    """What tells us a parcel was sent again. Each part is optional: a failure leaves it empty, never breaks the page.
    Order notes are read only for orders whose note or tags mention replacement / reshipping; only the order number they
    refer to (and a yes/no) is kept, the text is dropped at once. Also every tracking number on each fulfilment: a
    board row shows one number, but a fulfilment can list several, and one of them may be a parcel that another
    order's row owns (#8446 lists TBA336415473219, whose tracking row belongs to #8426)."""
    items: dict[str, set[str]] = {}
    numbers: dict[str, set[str]] = {}
    try:
        c = client()
        last: str | None = None
        while True:
            p = [("select", "id,items,tracking"), ("order", "id.asc")]
            if last:
                p.append(("id", f"gt.{last}"))
            page = c.select("shipments", p, limit=1000).rows
            for x in page:
                items[x["id"]] = {str(i.get("item_id")) for i in (x.get("items") or []) if isinstance(i, dict) and i.get("item_id")}
                nums = {str(n).strip().upper() for n in (x.get("tracking") or []) if str(n or "").strip()}
                if nums:
                    numbers[x["id"]] = nums
            if len(page) < 1000:
                break
            last = page[-1]["id"]
    except SupabaseError:
        items, numbers = {}, {}
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
    return items, replacements, notes, numbers


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


def loaded() -> bool:
    """True once a snapshot is cached, so reading the board will not wait for Supabase."""
    return _cache is not None


def reload_in_background() -> None:
    if _reloading.is_set():
        return
    _reloading.set()

    def work() -> None:
        try:
            snapshot(force=True)
            warm()
        except Exception:  # noqa: BLE001 - the saved copy stays in use; the next request tries again
            pass
        finally:
            _reloading.clear()
    threading.Thread(target=work, name="shipping-board-reload", daemon=True).start()


# The built board per brand. Building it from the snapshot (every parcel enriched, Amazon laid over it, the reship
# and delivered rules) takes ~0.2 s on a laptop and ~2 s on the hosting's small CPU, and every request used to do
# it. Now one build serves every request for that brand until the snapshot is reloaded, a team mark or outcome
# changes it, or BUILT_SECONDS pass (ages count in whole days). Parallel requests wait for one build.
# Once a brand has a board, a page never waits for the next one: when it is older than BUILT_SECONDS or the snapshot
# was reloaded, the old board answers while a new one is built in the background (as the snapshot itself does).
# Only a brand's first board, Refresh now (forget) and a team mark or outcome (forget_built) make a page wait.
_built: dict[str, tuple[float, Snapshot, Dataset]] = {}
_built_lock = threading.Lock()
_brand_locks: dict[str, threading.Lock] = {}
_rebuilding: set[str] = set()
_built_gen = 0          # +1 on every forget_built(): a build that started before it must not be saved after it


def _brand_lock(key: str) -> threading.Lock:
    with _built_lock:
        return _brand_locks.setdefault(key, threading.Lock())


def _build_and_keep(key: str, snap: Snapshot) -> Dataset:
    gen = _built_gen
    ds = build(key, snap=snap)
    if gen == _built_gen:
        _built[key] = (time.time(), snap, ds)
    return ds


def _rebuild_in_background(key: str, snap: Snapshot) -> None:
    with _built_lock:
        if key in _rebuilding:
            return
        _rebuilding.add(key)

    def work() -> None:
        try:
            with _brand_lock(key):
                _build_and_keep(key, snap)
        except Exception:  # noqa: BLE001 - the old board stays in use; the next request tries again
            logging.getLogger(__name__).warning("shipping board rebuild failed", exc_info=True)
        finally:
            with _built_lock:
                _rebuilding.discard(key)
    threading.Thread(target=work, name=f"shipping-board-build-{key}", daemon=True).start()


def dataset(brand: str | None, refresh: bool = False) -> Dataset:
    key = brand or "all"
    snap = snapshot(force=refresh)
    hit = _built.get(key)
    if hit and (not refresh or hit[1] is snap):
        if hit[1] is not snap or time.time() - hit[0] >= BUILT_SECONDS:
            _rebuild_in_background(key, snap)
        return hit[2]
    with _brand_lock(key):
        hit = _built.get(key)
        if hit and hit[1] is snap:
            return hit[2]
        return _build_and_keep(key, snap)


def forget_built() -> None:
    """Drop every built board (a team mark, an outcome or a new snapshot changes what it shows)."""
    global _built_gen
    _built_gen += 1
    _built.clear()


def _memoized(fn: Any) -> Any:
    """Work a report out once per built board (keyed by its arguments) instead of on every request: the Overview,
    Checks and Analytics figures took 0.3-0.7 s each on the hosting's CPU, and one heavy request held up every other
    request behind it. The board is rebuilt when its data changes, and annotate() clears this when it edits the board
    in place. Callers must not change the dict they get back (every request shares it)."""
    @wraps(fn)
    def wrapper(ds: Dataset, *args: Any) -> Any:
        key = (fn.__name__, *args)
        hit = ds.memo.get(key)
        if hit is None:
            hit = ds.memo[key] = fn(ds, *args)
        return hit
    return wrapper


def warm() -> None:
    """Build the default (all brands) board in the background, so the next page does not wait for it."""
    try:
        dataset("all")
    except Exception:  # noqa: BLE001 - a page builds it itself if this fails
        logging.getLogger(__name__).warning("shipping board warm-up failed", exc_info=True)


def forget() -> None:
    global _cache
    with _lock:
        _cache = None
    forget_built()


def apply_mark(tracking_id: str, mark: str | None) -> None:
    """Show a team mark at once in the saved copy (the next refresh reloads it from Supabase anyway)."""
    cached = _cache
    if not cached:
        return
    at = datetime.now(UTC).isoformat()
    for r in cached[1].rows:
        if r.get("tracking_id") == tracking_id:
            r["team_mark"], r["team_mark_at"] = mark, at if mark else None
    forget_built()                       # the snapshot changed in place: rebuild on the next request


# ------------------------------------------------------------------------------------------------ enrichment
@dataclass
class Dataset:
    rows: list[dict[str, Any]]          # dispatched parcels: active (one section each) and delivered
    everything: list[dict[str, Any]]    # every dispatched parcel, before exclusions (order detail)
    now: datetime
    brand: str
    snap: Snapshot
    marks: dict[tuple[str, int], dict[str, Any]]
    reshipped: list[dict[str, Any]] = None  # type: ignore[assignment]  # old parcels the team sent again
    resolved: list[dict[str, Any]] = None   # type: ignore[assignment]  # lost / returned / refunded / couldn't deliver
    memo: dict[tuple[Any, ...], Any] = field(default_factory=dict, repr=False)  # figures already worked out (_memoized)

    @property
    def active(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["cat"] != "delivered"]


DELIVERED_SCAN = re.compile(r"^\s*delivered", re.I)


def _enrich(s: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """One dispatched parcel with its clock and the facts the sections are decided from. None for a row this page does
    not track: an order not sent yet, or tracking that closed without an outcome."""
    status = (s.get("status") or "").lower()
    if status == "expired":
        return None                     # tracking closed without an outcome: nothing to act on
    carrier = s.get("carrier_name") or ""
    tracking = s.get("tracking_number") or ""
    created, shipped = ts(s.get("placed_at")), ts(s.get("shipped_at"))
    if s["row_kind"] == "order":
        shipped = None
    last_scan, delivered_at = ts(s.get("last_scan_at")), ts(s.get("delivered_at"))
    mark = (s.get("team_mark") or "").lower()
    manual = {"status": mark, "at": s.get("team_mark_at")} if mark in TEAM_STATES else None
    # delivered by the parcel's own evidence: its status, a last scan that says so, or the team's mark
    scan_says = bool(DELIVERED_SCAN.match(s.get("last_scan_text") or ""))
    delivered = status == "delivered" or scan_says or mark == "delivered"
    if delivered and not delivered_at and scan_says:
        delivered_at = last_scan
    cat, days, stage = flow_category(shipped, last_scan, now, delivered)
    if stage == "pre_dispatch":
        return None                     # not sent yet: not tracked on this page
    if not delivered and (whole_days(shipped, now) or 0) > TRACK_DAYS:
        return None                     # sent more than TRACK_DAYS ago and never confirmed: out of this page's window
    exc = (s.get("raw_status") or status).lower() if status in ("exception", "returned") else ""
    fin = (s.get("financial_status") or "").upper()
    missing = s["row_kind"] in ("shipment", "tracking", "amazon") and not tracking
    # a number no carrier has said anything about (no status, no scan) after the grace days: the number is wrong,
    # or was never handed to the carrier. Any status or scan at all means the number is real.
    invalid = (not delivered and not missing and status in ("", "pending") and last_scan is None
               and (whole_days(shipped, now) or 0) >= NO_SCAN_GRACE_DAYS)
    return {
        **s,
        "brand": STORE_BRAND.get(s.get("store") or "", s.get("store")),
        "order_number": s.get("order_name") or str(s.get("order_id")),
        "carrier_name": carrier,
        "tracking_number": tracking,
        "normalized_tracking_status": status,
        "created": created, "shipped": shipped,
        "lastScan": last_scan, "deliveredAt": delivered_at, "expected": day_end(s.get("eta")),
        "cat": cat, "band": cat, "agingCat": cat, "days": days, "stage": stage, "scanAge": whole_days(last_scan, now),
        "exc": exc, "manual": manual, "invalid": invalid, "issues": [],
        # a fulfilment row with a number shares another order's parcel (two orders sent in one box), so it has tracking
        "missingTracking": missing,
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
        if m and m.get("outcome") in TEAM_OUTCOMES:
            r["resolved"] = {"outcome": m["outcome"], "label": OUTCOMES[m["outcome"]], "by": "team",
                             "who": m.get("outcome_by"), "at": m.get("outcome_at"), "detail": ""}
        elif r["manual"] and r["manual"]["status"] in ("lost", "failed"):
            o = r["manual"]["status"]
            r["resolved"] = {"outcome": o, "label": OUTCOMES[o], "by": "team", "who": None, "at": r["manual"].get("at"),
                             "detail": "Team mark on the parcel."}
        else:
            o = carrier_outcome(r)
            if o:
                r["resolved"] = {"outcome": o, "label": OUTCOMES[o], "by": "carrier", "who": r.get("carrier_name") or None,
                                 "at": iso(r["lastScan"]), "detail": r.get("last_scan_text") or r.get("raw_status") or ""}


def _amazon_says_delivered(r: dict[str, Any]) -> bool:
    amazon = r.get("amazon_status") or ""
    return bool(AMAZON_DELIVERED.search(amazon) and not AMAZON_NOT_DELIVERED.search(amazon))


def _mark_order_delivered(everything: list[dict[str, Any]], numbers: dict[str, set[str]] | None = None) -> None:
    """An order that has arrived is not a problem: once ANY parcel of it is delivered (Shopify, the carrier, Amazon's
    MCF data, or a last scan that says "Delivered"), every other open parcel of that order is resolved as Delivered
    ("order delivered"). That covers a fulfilment with no tracking number on a delivered order (# RBP6462), a parcel
    whose replacement arrived (#5680), and an extra Amazon parcel (#7254). It leaves Critical, exceptions, Checks,
    Reshipped and Unfulfilled. A parcel whose own last scan says delivered counts as delivered too. Two orders sent in
    one box share one tracking number (CPC #6948 and #6949): once that number is delivered on either order, it is
    delivered on both. The same holds for any number on the parcel's Shopify fulfilment (`numbers`), not only the
    one its row shows."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in everything:
        if not r["excluded"]:
            by.setdefault((r.get("store") or "", _digits(r["order_number"])), []).append(r)
    shared = {((r.get("store") or ""), r["tracking_number"].upper()): r for r in everything
              if r["cat"] == "delivered" and r["tracking_number"] and not r["excluded"]}
    numbers = numbers or {}
    for r in everything:
        if r["cat"] == "delivered" or r.get("resolved") or r["excluded"]:
            continue
        own = numbers.get(str(r.get("shipment_id") or ""), set()) | ({r["tracking_number"].upper()} if r["tracking_number"] else set())
        x = next((shared[k] for k in sorted(((r.get("store") or ""), n) for n in own) if k in shared and shared[k] is not r), None)
        if x is not None:
            when = x.get("deliveredAt") or x.get("lastScan")
            parcel = f"{x['carrier_name'] or 'The carrier'} {x['tracking_number']}"
            on = f" on {when.date().isoformat()}" if when else ""
            same = (x.get("store"), _digits(x["order_number"])) == (r.get("store"), _digits(r["order_number"]))
            r["resolved"] = {"outcome": "delivered", "label": "Delivered", "by": "order", "who": None, "at": iso(when),
                             "detail": (f"The order was delivered ({parcel}{on})." if same else
                                        f"Sent together with order {x['order_number']}: {parcel} was delivered{on}, and "
                                        f"this order's Shopify fulfilment lists that number.")}
    for parcels in by.values():
        done = [r for r in parcels if r["cat"] == "delivered" or (r.get("resolved") or {}).get("outcome") == "delivered"]
        word = next((r for r in parcels if _amazon_says_delivered(r)), None)
        if not done and word is not None:   # Amazon's own word on the order ("Package delivered near the front door")
            for r in parcels:
                if r["cat"] != "delivered" and not r.get("resolved"):
                    r["resolved"] = {"outcome": "delivered", "label": "Delivered", "by": "order", "who": None,
                                     "at": word.get("amazon_at"),
                                     "detail": f"Amazon says \"{(word.get('amazon_status') or '')[:80]}\"."}
            continue
        if not done:
            continue
        delivered_by = {(r["tracking_number"] or "").upper(): r for r in done if r["tracking_number"]}
        for r in parcels:
            if r["cat"] == "delivered" or r.get("resolved"):
                continue
            rs = r.get("reshipped") or {}
            new = delivered_by.get((rs.get("newTracking") or "").upper()) if rs else None
            via = [new] if new else [x for x in done if x is not r]
            times: list[datetime] = [t for t in (x.get("deliveredAt") or x.get("lastScan") for x in via) if t]
            last = max(times, default=None)
            what = ", ".join(f"{x['carrier_name'] or 'Unknown'} {x['tracking_number']}".strip()
                             for x in via if x["tracking_number"]) or "another parcel"
            this = "This parcel has no tracking number" if r["missingTracking"] else "This parcel is still open"
            r["resolved"] = {"outcome": "delivered", "label": "Delivered", "by": "order", "who": None, "at": iso(last),
                             "detail": (f"The parcel that replaced it was delivered ({what})" if new else
                                        f"The order was delivered ({what})")
                                       + (f", last on {last.date().isoformat()}" if last else "")
                                       + f". {this} in Shopify or Amazon."}


def build(brand: str | None, now: datetime | None = None, snap: Snapshot | None = None) -> Dataset:
    stores = brand_stores(brand)
    snap = snap or snapshot()
    now = now or datetime.now(UTC)
    source = amazon_mcf.overlay([s for s in snap.rows if s.get("store") in stores], snap.mcf)
    everything = [e for e in (_enrich(s, now) for s in source) if e]
    marks = _marks(stores)
    _mark_reshipped(everything, snap)
    _mark_resolved(everything, marks)
    _mark_order_delivered(everything, snap.numbers)
    for r in everything:                  # delivered by any evidence: delivered, never "resolved"
        if (r.get("resolved") or {}).get("outcome") == "delivered":
            r["deliveredBy"] = r.pop("resolved")
            r["cat"] = "delivered"
    rows = [r for r in everything if not r["excluded"] and not r.get("reshipped") and not r.get("resolved")]
    _assign_sections(rows, now)
    reshipped = [r for r in everything if not r["excluded"] and r.get("reshipped") and not r.get("resolved")
                 and r["cat"] != "delivered"]
    resolved = [r for r in everything if not r["excluded"] and r.get("resolved")]
    return Dataset(rows, everything, now, brand or "all", snap, marks, reshipped, resolved)


def _assign_sections(rows: list[dict[str, Any]], now: datetime) -> None:
    """Each active parcel's own section, then every active parcel of an order moves to the order's first section, so
    an order is listed (and checked) once."""
    active = [r for r in rows if r["cat"] != "delivered"]
    dup = Counter(r["tracking_number"].upper() for r in active if r["tracking_number"])
    for r in active:
        issues: list[tuple[str, str]] = []
        if r["missingTracking"]:
            issues.append(("missing_tracking", f"Dispatched {whole_days(r['shipped'], now) or 0} days ago with no tracking "
                           f"number. Add it in Shopify."))
        elif r["invalid"]:
            issues.append(("invalid_tracking", f"{r['carrier_name'] or 'The carrier'} has reported nothing on "
                           f"{r['tracking_number']} since it was dispatched {whole_days(r['shipped'], now) or 0} days ago. "
                           f"Check the number."))
        if r["row_kind"] == "amazon" and r.get("amazon_extra"):
            issues.append(("amazon_tracking_missing", f"Amazon (MCF) sent a parcel"
                           f"{' (tracking ' + r['tracking_number'] + ')' if r['tracking_number'] else ''} that is not on the "
                           f"Shopify order, which lists {', '.join(r['amazon_extra'])}. Check whether the order was split or "
                           f"sent twice, and add the Amazon tracking number to the Shopify order."))
        elif r["row_kind"] == "amazon":
            issues.append(("amazon_not_in_shopify", f"Amazon shipped it {whole_days(r['shipped'], now) or 0} days ago"
                           f"{' (tracking ' + r['tracking_number'] + ')' if r['tracking_number'] else ''}; Shopify still shows "
                           f"the order unfulfilled. Mark it fulfilled in Shopify."))
        if r["tracking_number"] and dup[r["tracking_number"].upper()] > 1:
            issues.append(("duplicate_tracking", f"Tracking number {r['tracking_number']} is used on "
                           f"{dup[r['tracking_number'].upper()]} parcels."))
        r["issues"] = issues
        own = min((EXC_TYPES[k]["section"] for k, _ in issues), key=RANK.__getitem__, default=r["band"])
        r["ownCat"] = r["cat"] = own
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in active:
        by.setdefault((r.get("store") or "", _digits(r["order_number"])), []).append(r)
    for parcels in by.values():
        top = min((r["cat"] for r in parcels), key=RANK.__getitem__)
        for r in parcels:
            r["cat"] = top


def _digits(name: str) -> str:
    return "".join(ch for ch in (name or "") if ch.isdigit())


def _mark_reshipped(rows: list[dict[str, Any]], snap: Snapshot) -> None:
    """Flag a parcel (or a not-dispatched order) that never arrived but was sent again, so it leaves the delay figures.
    Three signals, strongest first:
      1. a replacement order says "replacement for #NNNN" (same store): every undelivered parcel of #NNNN placed
         before the replacement;
      2. a later parcel of the same order carries the same Shopify items;
      3. the order's own note says reshipped / resent and a later parcel exists: the earlier undelivered ones;
      4. a second Amazon MCF order; 5. another carrier delivered the order (the open parcel of a different carrier)."""
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

    # 5. the order was delivered by another parcel (from Shopify, Amazon's MCF data or the carrier), so an open parcel
    #    that stopped moving is the attempt that was replaced. Only a parcel sent BEFORE that delivery and with no scan
    #    since: one sent later (an exchange, more items) or still moving (a split) stays on the board. The delivered
    #    parcel must be from a different carrier, or (same carrier) sent RESHIP_GAP_DAYS or more after the open one:
    #    parcels sent together are a split, and one of them missing is a real problem.
    def carrier(r: dict[str, Any]) -> str:
        c = (r.get("carrier_name") or "").strip().lower()
        return "" if c in ("", "unknown carrier", "other") else c

    gap = amazon_mcf.RESHIP_GAP_DAYS * DAY
    for parcels in by_order.values():
        delivered = [r for r in parcels if r["cat"] == "delivered" and r.get("deliveredAt")]
        for old in parcels:
            if old["cat"] == "delivered" or old["row_kind"] not in ("tracking", "shipment", "amazon"):
                continue
            sent_at = old.get("shipped")
            if not sent_at:
                continue
            moved_at = old.get("lastScan") or sent_at
            other = [n for n in delivered if _replaces(old, n, sent_at, moved_at, gap, carrier)]
            if not other:
                continue
            n = max(other, key=lambda x: iso(x.get("deliveredAt") or x.get("shipped")) or "")
            when = n.get("deliveredAt")
            how = "delivered_by_other_carrier" if carrier(n) != carrier(old) else "delivered_by_later_parcel"
            resent = ""
            if how == "delivered_by_later_parcel" and n.get("tracking_number") and n.get("shipped"):
                resent = f" ({n['tracking_number']}, sent {n['shipped'].date().isoformat()})"
            on = f" on {when.date().isoformat()}" if when else ""
            flag(old, how, f"{n['carrier_name'] or 'Another parcel'} delivered this order{on}{resent}.",
                 {"order": n["order_number"], "tracking": n["tracking_number"], "carrier": n["carrier_name"],
                  "status": n["cat"], "at": iso(when or n.get("shipped"))})


def _replaces(old: dict[str, Any], n: dict[str, Any], sent_at: datetime, moved_at: datetime, gap: float,
              carrier: Any) -> bool:
    """Rule 5: delivered parcel `n` replaced the open parcel `old` (sent at `sent_at`, last moved at `moved_at`)."""
    if n is old or (n["deliveredAt"] - sent_at).total_seconds() < 2 * DAY or moved_at > n["deliveredAt"]:
        return False
    if carrier(n) and carrier(old) and carrier(n) != carrier(old):
        return True
    return bool(n.get("shipped")) and (n["shipped"] - sent_at).total_seconds() >= gap


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


AMAZON_DELIVERED = re.compile(r"\bdelivered\b", re.I)
AMAZON_NOT_DELIVERED = re.compile(r"\b(not|un)\s*deliver|undeliverable|out for delivery|attempt", re.I)


def delivered_orders(ds: Dataset) -> set[tuple[str, str]]:
    """(store, order number digits) of every order that has arrived, by any source. Every parcel of such an order is
    already delivered on the board (build); this is the same fact as a set, for checks from outside."""
    return {(r.get("store") or "", _digits(r["order_number"])) for r in ds.everything if r["cat"] == "delivered"}


def exception_rows(ds: Dataset) -> list[dict[str, Any]]:
    """Every hand-check issue of the parcels in the Tracking missing, Invalid tracking and Fix in Shopify sections."""
    out: list[dict[str, Any]] = []
    for r in ds.active:
        if r["cat"] not in HAND_CHECKS:
            continue
        for kind, detail in r["issues"]:
            t = EXC_TYPES[kind]
            out.append({"order": r["order_number"], "key": r["key"], "type": kind, "label": t["label"],
                        "severity": t["severity"], "detail": detail, "carrier": r["carrier_name"] or "Unknown",
                        "tracking": "" if r["missingTracking"] else r["tracking_number"], "days": r["days"],
                        "brand": r["brand"], "shopifyUrl": shopify_url(r), "section": r["cat"]})
    sev = {"high": 0, "medium": 1}
    out.sort(key=lambda x: (RANK[x["section"]], sev[x["severity"]], -(x["days"] or 0), x["order"]))
    return out


def exception_orders(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per order: its issues (one tag each, most severe first) across all its parcels. Keeps the first
    issue's fields at the top level so a row still reads like a single issue."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for x in issues:                         # issues arrive sorted: section, severity, then age
        by.setdefault((x["brand"] or "", x["order"]), []).append(x)
    out = []
    for xs in by.values():
        first = xs[0]
        seen: set[tuple[str, str]] = set()
        tags = []
        for x in xs:                         # the same issue twice (same type and text) is one tag
            if (x["type"], x["detail"]) not in seen:
                seen.add((x["type"], x["detail"]))
                tags.append(x)
        out.append({**first, "types": list(dict.fromkeys(x["type"] for x in tags)),
                    "carrier": " / ".join(dict.fromkeys(x["carrier"] for x in tags)),
                    "tracking": ", ".join(dict.fromkeys(x["tracking"] for x in tags if x["tracking"])),
                    "days": max((x["days"] for x in tags if x["days"] is not None), default=None),
                    "severity": "high" if any(x["severity"] == "high" for x in tags) else first["severity"],
                    "issues": [{k: x[k] for k in ("type", "label", "severity", "detail", "carrier", "tracking", "key")}
                               for x in tags]})
    return out


@_memoized
def checks(ds: Dataset) -> dict[str, Any]:
    issues = exception_rows(ds)
    rows = exception_orders(issues)
    return {"reshipped": reshipped_report(ds),
            "counts": {s: len({(r["brand"], r["order_number"]) for r in ds.active if r["cat"] == s}) for s in HAND_CHECKS},
            # total = orders (one row each); counts = orders with that type, so an order with two tags counts in both
            "exceptions": {"total": len(rows), "issues": len(issues),
                           "counts": {k: sum(1 for r in rows if k in r["types"]) for k in EXC_TYPES},
                           "types": [{"key": k, "label": v["label"], "severity": v["severity"]} for k, v in EXC_TYPES.items()],
                           "rows": rows}}


def kpis(ds: Dataset) -> list[dict[str, Any]]:
    active = ds.active
    counts = Counter(r["cat"] for r in active)
    spec = (("", "Total active shipments", "neutral"), ("on_track", "On track (0-3 days)", "good"),
            ("yellow", "Yellow 4-5 days", "warn"), ("orange", "Orange 6-8 days", "orange"),
            ("red", "Critical 9+ days", "bad"), ("tracking_missing", "Tracking missing", "bad"),
            ("invalid", "Invalid tracking", "info"), ("checks", "Fix in Shopify", "warn"),
            ("reshipped", "Reshipped, old parcel still open", "info"))
    values = {"": len(active), "reshipped": len(ds.reshipped or [])}
    return [{"key": k, "label": label, "value": values[k] if k in values else counts.get(k, 0), "tone": tone}
            for k, label, tone in spec]


RESHIP_HOW = {"replacement_order": "Replacement order", "sent_again": "Same items sent again",
              "note_says_reshipped": "Note says reshipped", "second_amazon_order": "Second Amazon order",
              "delivered_by_other_carrier": "Delivered by another carrier",
              "delivered_by_later_parcel": "Delivered by a later parcel"}


def reshipped_report(ds: Dataset) -> dict[str, Any]:
    rows = []
    for r in sorted(ds.reshipped or [], key=lambda r: -(r["days"] or 0)):
        rs = r["reshipped"]
        rows.append({"order": r["order_number"], "key": r["key"], "brand": r["brand"], "carrier": r["carrier_name"] or "—",
                     "shopifyUrl": shopify_url(r), "tracking": "" if r["missingTracking"] else r["tracking_number"],
                     "oldCat": r["band"], "oldStatus": r["normalized_tracking_status"] or "",
                     "lastScan": r.get("last_scan_text") or "", "days": r["days"], "stage": r["stage"],
                     "how": rs["how"], "howLabel": RESHIP_HOW.get(rs["how"], rs["how"]), "detail": rs["detail"],
                     "newOrder": rs.get("newOrder"), "newTracking": rs.get("newTracking"), "newCarrier": rs.get("newCarrier"),
                     "newStatus": rs.get("newStatus"), "newAt": rs.get("newAt"),
                     "action": "Close the old fulfilment in Shopify (or cancel the Amazon MCF order) so it stops showing as open."})
    return {"total": len(rows), "rows": rows,
            "counts": {k: sum(1 for x in rows if x["how"] == k) for k in RESHIP_HOW},
            "rule": "A parcel that never arrived but was sent again: a replacement order names it, a later parcel of the same "
                    "order carries the same items, the order note says it was reshipped, a second Amazon order was sent, "
                    "or another parcel delivered the order. These are left out of every delay figure."}


HOME_TOP = 4


def home_figures(ds: Dataset, brands: list[str]) -> dict[str, Any]:
    """Shipping figures for the Home page, from the same board the Shipping page shows (so the two always agree):
    the selected brands together (`all`), each brand on its own (`byBrand`, never added across brands by mistake) and
    the problems (Critical, or waiting for a hand check), longest on the clock first."""
    since = ds.now - timedelta(days=30)

    def problem(r: dict[str, Any]) -> bool:
        return r["cat"] == "red" or r["cat"] in HAND_CHECKS

    def figures(rows: list[dict[str, Any]]) -> dict[str, Any]:
        active = [r for r in rows if r["cat"] != "delivered"]
        return {"active": len(active), "inTransit": len(active),
                "delivered30d": sum(1 for r in rows if r["cat"] == "delivered" and r["deliveredAt"] and r["deliveredAt"] >= since),
                "problems": sum(1 for r in active if problem(r)), "critical": sum(1 for r in active if r["cat"] == "red"),
                "handChecks": sum(1 for r in active if r["cat"] in HAND_CHECKS)}

    rows = [r for r in ds.rows if r["brand"] in brands]
    top = sorted((r for r in rows if r["cat"] != "delivered" and problem(r)), key=lambda r: (-(r["days"] or 0), r["key"]))[:HOME_TOP]
    allv = {**figures(rows), "asOf": iso(ds.now),
            "top": [{"order": r["order_number"], "brand": r["brand"], "carrier": r["carrier_name"] or "Unknown", "days": r["days"],
                     "place": r.get("last_scan_place") or "", "trackingId": r.get("tracking_id") or r["key"],
                     "label": LABELS.get(r["cat"], r["cat"])} for r in top]}
    return {"all": allv, "byBrand": {b: figures([r for r in rows if r["brand"] == b]) for b in brands}}


AWAITING_SCAN = ("", "pending", "info_received")


def journey(ds: Dataset) -> list[dict[str, Any]]:
    """Where every dispatched parcel is, left to right, for the Overview journey strip. The three parcel stages split
    the active parcels by their tracking status, so they add up to the active total. `flags` are the sections sitting
    in that stage; `cat`/`status` say which list to open."""
    sent = ds.active
    waiting = [r for r in sent if (r["normalized_tracking_status"] or "") in AWAITING_SCAN]
    out = [r for r in sent if r["normalized_tracking_status"] == "out_for_delivery"]
    moving = [r for r in sent if (r["normalized_tracking_status"] or "") not in (*AWAITING_SCAN, "out_for_delivery")]

    def flag(label: str, n: int, tone: str, cat: str = "") -> list[dict[str, Any]]:
        return [{"label": label, "value": n, "tone": tone, "cat": cat}] if n else []

    def flags(lst: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return (flag("tracking missing", sum(1 for r in lst if r["cat"] == "tracking_missing"), "crit", "tracking_missing")
                + flag("invalid tracking", sum(1 for r in lst if r["cat"] == "invalid"), "info", "invalid")
                + flag("critical", sum(1 for r in lst if r["cat"] == "red"), "crit", "red"))

    return [
        {"key": "dispatched", "label": "Sent, no carrier scan yet", "value": len(waiting), "flags": flags(waiting)},
        {"key": "in_transit", "label": "In transit", "value": len(moving), "flags": flags(moving)},
        {"key": "out_for_delivery", "label": "Out for delivery", "value": len(out), "flags": flags(out)},
        # same rule as delivery_report(ds, 30), so it matches the Overview's "Delivered, last 30 days"
        {"key": "delivered", "label": "Delivered, last 30 days",
         "value": sum(1 for r in ds.rows if r["cat"] == "delivered" and r["deliveredAt"] and r["shipped"]
                      and r["deliveredAt"] >= ds.now - timedelta(days=30)), "flags": []},
    ]


@_memoized
def summary(ds: Dataset) -> dict[str, Any]:
    active = ds.active
    critical = sum(1 for r in active if r["cat"] == "red")
    c = checks(ds)
    dr = delivery_report(ds, 30)
    return {
        "journey": journey(ds),
        "delivery30": {"delivered": dr["delivered"], "onTimePct": dr["onTimePct"], "avgDays": dr["avgDays"],
                       "withPromisedDate": dr["withPromisedDate"]},
        "kpis": kpis(ds), "activeTotal": len(active), "critical": critical,
        "delivered": sum(1 for r in ds.rows if r["cat"] == "delivered"),
        "stage": {"dispatched": len(active), "delivered": sum(1 for r in ds.rows if r["cat"] == "delivered")},
        "banner": (f"CRITICAL: {critical} shipment(s) have had no carrier update for {THRESH['red']}+ days. Escalate today."
                   if critical else ""),
        "valueAtRisk": value_at_risk(ds), "checks": c["counts"], "exceptions": c["exceptions"]["total"],
        "thresholds": {**THRESH, "noScanGrace": NO_SCAN_GRACE_DAYS},
        "totals": {"shipments": len(ds.everything), "afterExclusions": len(ds.rows)},
        "deliveredWindowDays": DELIVERED_KEEP_DAYS,
    }


def carriers_report(ds: Dataset) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {}
    for r in ds.active:
        c = by.setdefault(r["carrier_name"] or "Unknown", {"n": 0, "crit": 0, "hand": 0, "days": [], "cats": Counter()})
        c["n"] += 1
        c["cats"][r["cat"]] += 1
        if r["days"] is not None:
            c["days"].append(r["days"])
        if r["cat"] == "red":
            c["crit"] += 1
        if r["cat"] in HAND_CHECKS:
            c["hand"] += 1
    scored = []
    for name, c in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        pct = round(c["crit"] / c["n"] * 100)
        scored.append({"carrier": name, "active": c["n"], "critical": c["crit"], "criticalPct": pct, "handChecks": c["hand"],
                       "avgDays": round(sum(c["days"]) / len(c["days"])) if c["days"] else None,
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


@_memoized
def analytics(ds: Dataset, period: int) -> dict[str, Any]:
    active = ds.active
    crit = sum(1 for r in active if r["cat"] == "red")
    hand = sum(1 for r in active if r["cat"] in HAND_CHECKS)
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
    tips: list[str] = []
    if crit:
        tips.append(f"{crit} active shipments have had no carrier update for {THRESH['red']}+ days. Escalate these first "
                    "(filter: Critical).")
    worst = max(car, key=lambda c: c["critical"], default=None)
    if worst and worst["critical"]:
        tips.append(f"{worst['carrier']} has the most critical shipments ({worst['critical']}). Check them with this carrier first.")
    if count["tracking_missing"]:
        tips.append(f"{count['tracking_missing']} parcels were dispatched without a tracking number. Add it in Shopify.")
    if count["invalid"]:
        tips.append(f"{count['invalid']} parcels have a tracking number no carrier has reported anything on. Check the numbers.")
    if count["checks"]:
        tips.append(f"{count['checks']} parcels need a fix in Shopify (Amazon shipments Shopify does not know about, or a "
                    "tracking number used twice).")
    return {
        "kpis": {"active": len(active), "critical": crit, "criticalPct": round(crit / len(active) * 100) if active else 0,
                 "onTrackPct": round(count["on_track"] / len(active) * 100) if active else 0,
                 "avgDays": round(sum(day_list) / len(day_list)) if day_list else None, "handChecks": hand,
                 "carriersInUse": len({r["carrier_name"] or "Unknown" for r in active}),
                 "valueAtRisk": value_at_risk(ds)},
        "aging": [{"key": k, "label": AGING_LABELS[k], "value": count[k]} for k in AGING_KEYS],
        "weeks": [{"week": w, "value": n} for w, n in week_rows],
        "carriers": [{"carrier": c["carrier"], "critical": c["critical"], "other": c["active"] - c["critical"]} for c in car],
        "stage": [{"label": "Dispatched (active)", "value": len(active)},
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
        "priority": lambda r: (RANK.get(r["cat"], 9), -(r["days"] or 0)),
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


def _amazon_parcel(r: dict[str, Any]) -> bool:
    """Whether the order's Amazon (MCF) word belongs to THIS parcel. The board carries the order's latest Amazon status
    on every parcel of the order, so a FedEx parcel the team sent itself (# RBP8183) would otherwise read "Shipped by
    Amazon" with the USPS parcel's number."""
    if r["row_kind"] == "amazon":
        return True
    amazon_no = (r.get("amazon_tracking") or "").strip().upper()
    own = (r.get("tracking_number") or "").strip().upper()
    if amazon_no and own:
        return amazon_no == own
    carrier = r.get("carrier_name") or ""
    return r.get("kind") == "mcf" or "amazon" in carrier.lower() or unconfirmed_carrier(carrier)


def public_row(ds: Dataset, r: dict[str, Any], packages: dict[str, int]) -> dict[str, Any]:
    """What the browser receives for one parcel. No note text, no customer data beyond city and state."""
    amazon = _amazon_parcel(r)
    cat = ("delivered" if r["cat"] == "delivered" else "resolved" if r.get("resolved")
           else "reshipped" if r.get("reshipped") else r["cat"])
    own = r.get("ownCat") or r["band"]
    label = (LABELS["delivered"] if cat == "delivered" else f"Resolved: {r['resolved']['label']}" if cat == "resolved"
             else "Reshipped (old parcel)" if cat == "reshipped" else LABELS.get(cat, cat))
    if cat in SECTIONS and own != cat:      # listed with the rest of its order
        label += f" (this parcel: {LABELS.get(own, own)})"
    return {
        "key": r["key"], "order": r["order_number"], "tracking": r["tracking_number"], "carrier": r["carrier_name"],
        "cat": cat, "band": r["band"], "ownCat": own, "agingCat": r["band"], "label": label, "days": r["days"],
        "stage": r["stage"], "exception": r["exc"], "scanAge": r["scanAge"],
        "status": r["normalized_tracking_status"], "orderCreatedAt": iso(r["created"]), "dispatchedAt": iso(r["shipped"]),
        "lastScanAt": iso(r["lastScan"]), "lastScan": r.get("last_scan_text") or "", "expectedAt": r.get("eta"),
        "trackUrl": r.get("track_url") or "", "shopifyUrl": shopify_url(r), "manual": r["manual"],
        "packages": packages.get(r["order_number"], 1), "missingTracking": r["missingTracking"],
        "invalid": r["invalid"], "flagged": flagged(ds, r), "brand": r["brand"],
        "city": r.get("ship_city"), "state": r.get("ship_state"), "trackingId": r.get("tracking_id"),
        "kind": r.get("kind"), "rowKind": r["row_kind"],
        "amazonStatus": r.get("amazon_status") if amazon else None, "amazonAt": r.get("amazon_at") if amazon else None,
        "amazonRef": r.get("amazon_ref") if amazon else None, "amazonTracking": r.get("amazon_tracking") if amazon else None,
        "reshipped": r.get("reshipped"), "resolved": r.get("resolved"), "deliveredBy": r.get("deliveredBy"),
        "issues": [{"type": k, "label": EXC_TYPES[k]["label"], "detail": d} for k, d in r.get("issues") or []],
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
            "outcome": m.get("outcome") if m.get("outcome") in TEAM_OUTCOMES else None,
            "outcomeLabel": OUTCOMES.get(m.get("outcome") or ""), "outcomeAt": m.get("outcome_at"), "outcomeBy": m.get("outcome_by")}


def order_detail(ds: Dataset, order: str) -> dict[str, Any] | None:
    pkgs = _find(ds, order)
    if not pkgs:
        return None
    first = pkgs[0]
    parcels = pkgs
    ev = _events([p["tracking_id"] for p in parcels if p.get("tracking_id")])
    counts = {order: len(parcels)}

    def action(r: dict[str, Any]) -> str:
        if r["cat"] == "delivered":
            by = r.get("deliveredBy")
            return f"Delivered. {by['detail']}" if by and by.get("detail") else ACTIONS["delivered"]
        if r.get("resolved"):
            rs = r["resolved"]
            who = (f"the team{' (' + rs['who'] + ')' if rs.get('who') else ''}" if rs["by"] == "team"
                   else f"the carrier ({rs.get('detail') or 'last update'})")
            return f"Resolved as {rs['label'].lower()} by {who}, so it is out of Critical and the delay figures. Nothing more to do here."
        if r.get("reshipped"):
            return f"Sent again: {r['reshipped']['detail']} Close the old fulfilment in Shopify so it stops showing as open."
        if r.get("issues"):
            return " ".join(d for _, d in r["issues"])
        return ACTIONS.get(r["band"], "Review manually.")

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
        if outcome not in TEAM_OUTCOMES:
            raise HttpError(400, f"Outcome must be one of: {', '.join(TEAM_OUTCOMES)}.", "bad_request")
        run("UPDATE shipping_order_marks SET outcome = ?, outcome_at = ?, outcome_by = ? WHERE store = ? AND order_id = ?",
            outcome, at, by, store, oid)
    elif action == "clear_outcome":
        run("UPDATE shipping_order_marks SET outcome = NULL, outcome_at = NULL, outcome_by = NULL WHERE store = ? AND order_id = ?",
            store, oid)
    else:
        raise HttpError(400, "Unknown action.", "bad_request")
    if action in ("outcome", "clear_outcome"):    # the outcome moves parcels between lists: rebuild them
        fresh = build(ds.brand, now=ds.now, snap=ds.snap)
        ds.rows, ds.everything, ds.marks, ds.reshipped, ds.resolved = (
            fresh.rows, fresh.everything, fresh.marks, fresh.reshipped, fresh.resolved)
    else:
        ds.marks = _marks(brand_stores(ds.brand))
    ds.memo.clear()                      # this board changed in place: its figures must be worked out again
    forget_built()                       # other brands' boards still show the old mark: rebuild them
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
    return to_csv(["brand", "order_number", "carrier_name", "tracking_number", "section", "days_since_last_update",
                   "tracking_status", "order_created_at", "dispatched_at", "last_scan_at", "last_scan",
                   "promised_delivery", "tracking_url"],
                  [[r["brand"], r["order_number"], r["carrier_name"], r["tracking_number"], r["cat"], r["days"],
                    r["normalized_tracking_status"], r["created"], r["shipped"], r["lastScan"],
                    r.get("last_scan_text"), r.get("eta"), r.get("track_url")] for r in rows])


def csv_escalation(ds: Dataset) -> tuple[str, int]:
    rows = sorted((r for r in ds.active if r["cat"] == "red" or flagged(ds, r)), key=lambda r: -(r["days"] or 0))
    return to_csv(["brand", "order_number", "carrier_name", "tracking_number", "days_since_last_update", "reason",
                   "last_scan_at", "last_scan_description", "tracking_url"],
                  [[r["brand"], r["order_number"], r["carrier_name"], r["tracking_number"], r["days"],
                    "critical" if r["cat"] == "red" else "flagged by team",
                    r["lastScan"], r.get("last_scan_text"), r.get("track_url")] for r in rows]), len(rows)


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
    blank = [r for r in ds.active if r["row_kind"] == "shipment" and r["missingTracking"]][:3]
    has = next((r for r in ds.active if r["tracking_number"]), None)
    carrier = (import_carriers(ds) or ["USPS"])[0]
    lines = ["order_number,tracking_number,carrier"]
    lines += [f"{r['order_number']},EXAMPLE{1000001 + i},{r['carrier_name'] or carrier}" for i, r in enumerate(blank)]
    if has:
        lines.append(f"{has['order_number']},EXAMPLE2000002,{has['carrier_name'] or carrier}")
    lines.append(f"#000000,EXAMPLE3000003,{carrier}")
    lines.append(f"{blank[0]['order_number'] if blank else '#000001'},12,{carrier}")
    return "\n".join(lines)
