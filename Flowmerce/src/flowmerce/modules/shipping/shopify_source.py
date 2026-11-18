"""Read orders, fulfillments, tracking and carrier events straight from Shopify into ops.shopify_orders.

* Store keys come only from Flowmerce's own .env (RIDHI_SHOPIFY_* / CPC_SHOPIFY_*, via the SEO brand config) and
  never leave this server: nothing about them is written to Supabase.
* Nothing about the customer is read: only order number, dates, statuses, carrier, tracking numbers, line-item
  ids/quantities and carrier events (time, status, message, city/province/country).
* First run per store: one Shopify bulk export of the orders updated in the last 60 days (all a store app may
  read without the read_all_orders scope). Later runs: only orders updated since the last successful run (with
  a 10-minute overlap), plus a re-check of still-open parcels every OPEN_RECHECK_HOURS, because a new carrier
  event does not always change the order itself.
* Each store runs on its own: one store failing (keys refused, Shopify down) is recorded as a failed run for that
  store and never stops the other store or the Supabase refresh.
* Read-only towards Shopify.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from .supabase import SupabaseClient, SupabaseError, client

log = logging.getLogger("flowmerce.shipping.shopify")

STORE_BRAND = {"RBP": "ridhi", "CPC": "cpc"}       # ops.stores id -> SEO brand id (whose .env keys are used)
FIRST_RUN_DAYS = 60
OVERLAP_MINUTES = 10
OPEN_RECHECK_HOURS = 2
BULK_THRESHOLD = 250            # more changed orders than this -> one bulk export instead of paging
DETAIL_BATCH = 6                # fulfillments per detail query (keeps each query under Shopify's cost limit)
EVENTS_PER_FULFILLMENT = 100
CURSOR_PREFIX = "orders_updated_at:"

ORDER_FIELDS = """
  legacyResourceId name createdAt updatedAt cancelledAt displayFulfillmentStatus
  fulfillments {
    legacyResourceId status displayStatus createdAt updatedAt deliveredAt estimatedDeliveryAt inTransitAt
    service { handle }
    trackingInfo { company number url }
  }"""

DETAIL_QUERY = """query($ids: [ID!]!) { nodes(ids: $ids) { ... on Fulfillment {
  legacyResourceId
  events(first: %d, sortKey: HAPPENED_AT, reverse: true) {
    pageInfo { hasNextPage }
    nodes { id status happenedAt message city province country } }
  fulfillmentLineItems(first: 30) { nodes { quantity lineItem { id } } } } } }""" % EVENTS_PER_FULFILLMENT

TERMINAL_DISPLAY = {"DELIVERED", "CANCELED", "CANCELLED", "RETURNED"}


# ------------------------------------------------------------------------------------------- pure helpers
def _num(gid_or_id: Any) -> int | None:
    """'gid://shopify/FulfillmentEvent/123' or '123' -> 123."""
    m = re.search(r"(\d+)$", str(gid_or_id or ""))
    return int(m.group(1)) if m else None


def normalise_fulfillment(f: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """One Shopify GraphQL fulfillment (+ optional events/line items) in the shape the SQL refresh reads."""
    out: dict[str, Any] = {
        "id": _num(f.get("legacyResourceId")),
        "status": (f.get("status") or "").lower() or None,
        "display_status": f.get("displayStatus"),
        "created_at": f.get("createdAt"),
        "updated_at": f.get("updatedAt"),
        "delivered_at": f.get("deliveredAt"),
        "eta": f.get("estimatedDeliveryAt"),
        "in_transit_at": f.get("inTransitAt"),
        "service": (f.get("service") or {}).get("handle"),
        "tracking": [{"company": t.get("company"), "number": (t.get("number") or "").strip() or None, "url": t.get("url")}
                     for t in (f.get("trackingInfo") or [])],
        "items": [],
        "events": [],
        "events_complete": False,
    }
    if detail:
        out["events"] = [{"id": _num(e.get("id")), "status": e.get("status"), "at": e.get("happenedAt"),
                          "message": e.get("message"), "city": e.get("city"), "province": e.get("province"),
                          "country": e.get("country")}
                         for e in ((detail.get("events") or {}).get("nodes") or []) if e.get("happenedAt")]
        out["events_complete"] = not ((detail.get("events") or {}).get("pageInfo") or {}).get("hasNextPage", False)
        out["items"] = [{"item_id": _num((li.get("lineItem") or {}).get("id")), "qty": li.get("quantity")}
                        for li in ((detail.get("fulfillmentLineItems") or {}).get("nodes") or [])
                        if _num((li.get("lineItem") or {}).get("id")) and isinstance(li.get("quantity"), int)]
    return out


def needs_detail(f: dict[str, Any]) -> bool:
    """Events and line items are fetched for every fulfillment that is not cancelled."""
    return (f.get("status") or "").upper() not in ("CANCELLED", "ERROR", "FAILURE")


def reuse_detail(new: dict[str, Any], old: dict[str, Any] | None) -> bool:
    """A fulfillment that has not changed since the stored copy, and already had its events, needs no new fetch."""
    return bool(old and old.get("updated_at") == new.get("updatedAt") and "events" in old
                and (old.get("display_status") or "").upper() in TERMINAL_DISPLAY)


def order_row(store: str, node: dict[str, Any], fulfillments: list[dict[str, Any]], fetched_at: str) -> dict[str, Any]:
    return {
        "id": _num(node.get("legacyResourceId")),
        "store": store,
        "name": node.get("name") or "",
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "cancelled_at": node.get("cancelledAt"),
        "fulfillment_status": node.get("displayFulfillmentStatus"),
        "fulfillments": fulfillments,
        "fetched_at": fetched_at,
    }


def since_from_cursor(cursor: str | None, now: datetime) -> tuple[datetime, bool]:
    """(start of the window, is_first_run). Unknown/garbled cursor -> treated as a first run."""
    if cursor and cursor.startswith(CURSOR_PREFIX):
        try:
            ts = datetime.fromisoformat(cursor[len(CURSOR_PREFIX):].replace("Z", "+00:00"))
            return ts - timedelta(minutes=OVERLAP_MINUTES), False
        except ValueError:
            pass
    return now - timedelta(days=FIRST_RUN_DAYS), True


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------------------- Shopify access
def _brand(store: str):
    from ..seo.config import config
    return config.brands.get(STORE_BRAND.get(store, ""))


def store_configured(store: str) -> bool:
    from ..seo.integrations.shopify import configured
    b = _brand(store)
    return bool(b and configured(b))


def _gql_for(store: str) -> Callable[[str, dict | None], dict]:
    from ..seo.integrations.shopify import _gql
    b = _brand(store)
    return lambda q, v=None: _gql(b, q, v)


def _changed_ids(gql: Callable, since: datetime, limit: int) -> list[str] | None:
    """Order gids updated since `since`; None when there are more than `limit` (caller switches to bulk)."""
    ids: list[str] = []
    after = None
    while True:
        d = gql("""query($q: String!, $after: String) { orders(first: 250, after: $after, query: $q, sortKey: UPDATED_AT) {
                     pageInfo { hasNextPage endCursor } nodes { id } } }""",
                {"q": f"updated_at:>='{_iso(since)}'", "after": after})["orders"]
        ids += [n["id"] for n in d["nodes"]]
        if len(ids) > limit:
            return None
        if not d["pageInfo"]["hasNextPage"]:
            return ids
        after = d["pageInfo"]["endCursor"]


def _orders_by_id(gql: Callable, gids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(gids), 50):
        d = gql("query($ids: [ID!]!) { nodes(ids: $ids) { ... on Order { %s } } }" % ORDER_FIELDS, {"ids": gids[i:i + 50]})
        out += [n for n in d["nodes"] if n]
    return out


def _orders_bulk(gql: Callable, since: datetime, timeout_s: int = 900) -> list[dict[str, Any]]:
    inner = '{ orders(query: "updated_at:>=\'%s\'") { edges { node { %s } } } }' % (_iso(since), ORDER_FIELDS)
    d = gql("""mutation($q: String!) { bulkOperationRunQuery(query: $q) {
                 bulkOperation { id } userErrors { message } } }""", {"q": inner})["bulkOperationRunQuery"]
    if d["userErrors"]:
        raise RuntimeError("Shopify bulk export refused: " + "; ".join(e["message"] for e in d["userErrors"]))
    bid = d["bulkOperation"]["id"]
    deadline = time.monotonic() + timeout_s
    while True:
        s = gql("query($id: ID!) { node(id: $id) { ... on BulkOperation { status errorCode url } } }", {"id": bid})["node"]
        if s["status"] == "COMPLETED":
            break
        if s["status"] in ("FAILED", "CANCELED", "EXPIRED"):
            raise RuntimeError(f"Shopify bulk export {s['status'].lower()} ({s.get('errorCode') or 'no code'})")
        if time.monotonic() > deadline:
            raise RuntimeError("Shopify bulk export took too long; it will be retried on the next run.")
        time.sleep(3)
    if not s.get("url"):
        return []                                   # nothing matched
    rows: list[dict[str, Any]] = []
    with httpx.stream("GET", s["url"], timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _details(gql: Callable, fulfillment_ids: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for i in range(0, len(fulfillment_ids), DETAIL_BATCH):
        batch = [f"gid://shopify/Fulfillment/{x}" for x in fulfillment_ids[i:i + DETAIL_BATCH]]
        for n in gql(DETAIL_QUERY, {"ids": batch})["nodes"]:
            if n:
                out[_num(n["legacyResourceId"])] = n
    return out


# ------------------------------------------------------------------------------------------- Supabase side
def _last_cursor(c: SupabaseClient, store: str) -> str | None:
    rows = c.select("sync_runs", [("select", "cursor"), ("source", "eq.shopify"), ("kind", "eq.poll"),
                                  ("store", f"eq.{store}"), ("status", "eq.ok"),
                                  ("cursor", f"like.{CURSOR_PREFIX}*"), ("order", "started_at.desc")], limit=1).rows
    return rows[0]["cursor"] if rows else None


def _stored(c: SupabaseClient, ids: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for i in range(0, len(ids), 150):
        part = ids[i:i + 150]
        for r in c.select("shopify_orders", [("select", "id,fulfillments"),
                                             ("id", "in.(" + ",".join(map(str, part)) + ")")], limit=len(part)).rows:
            out[r["id"]] = {f.get("id"): f for f in (r.get("fulfillments") or [])}
    return out


def _open_order_gids(c: SupabaseClient, store: str, now: datetime) -> list[str]:
    """Orders with a parcel still on its way whose stored copy is older than OPEN_RECHECK_HOURS."""
    open_ids: set[int] = set()
    offset = 0
    while True:
        rows = c.select("shipments", [("select", "order_id"), ("store", f"eq.{store}"), ("origin", "eq.shopify_sync"),
                                      ("step", "in.(shipped,transit,out,exception)")], offset=offset, limit=1000).rows
        open_ids |= {r["order_id"] for r in rows}
        if len(rows) < 1000:
            break
        offset += 1000
    stale_before = _iso(now - timedelta(hours=OPEN_RECHECK_HOURS))
    created_after = _iso(now - timedelta(days=FIRST_RUN_DAYS - 1))
    ids = sorted(open_ids)
    stale: list[str] = []
    for i in range(0, len(ids), 150):
        part = ids[i:i + 150]
        rows = c.select("shopify_orders", [("select", "id"), ("id", "in.(" + ",".join(map(str, part)) + ")"),
                                           ("fetched_at", f"lt.{stale_before}"),
                                           ("created_at", f"gt.{created_after}")], limit=len(part)).rows
        stale += [f"gid://shopify/Order/{r['id']}" for r in rows]
    return stale


# ------------------------------------------------------------------------------------------- one store
def sync_store(store: str, triggered_by: str, c: SupabaseClient | None = None,
               gql: Callable | None = None, now: datetime | None = None) -> dict[str, Any]:
    c = c or client()
    now = now or datetime.now(timezone.utc)
    if gql is None and not store_configured(store):
        return {"store": store, "state": "not_configured"}
    gql = gql or _gql_for(store)
    try:
        run = c.insert_returning("sync_runs", {"source": "shopify", "kind": "poll", "store": store,
                                               "triggered_by": f"flowmerce:{triggered_by}"[:120]})
    except SupabaseError as e:
        if e.state == "conflict":
            return {"store": store, "state": "already_running"}
        raise
    run_id = run["id"]
    try:
        since, first = since_from_cursor(_last_cursor(c, store), now)
        gids = _changed_ids(gql, since, BULK_THRESHOLD)
        if gids is None:
            nodes = _orders_bulk(gql, since)
            mode = "bulk"
        else:
            recheck = [g for g in _open_order_gids(c, store, now) if g not in set(gids)]
            nodes = _orders_by_id(gql, gids + recheck)
            mode = "changed" if not recheck else f"changed+{len(recheck)} open re-checked"
        ids = [_num(n.get("legacyResourceId")) for n in nodes]
        stored = _stored(c, [i for i in ids if i])
        want = [_num(f["legacyResourceId"]) for n in nodes for f in (n.get("fulfillments") or [])
                if needs_detail(f) and not reuse_detail(f, stored.get(_num(n["legacyResourceId"]), {}).get(_num(f["legacyResourceId"])))]
        details = _details(gql, [w for w in want if w])
        fetched_at = _iso(now)
        rows = []
        max_updated = None
        for n in nodes:
            oid = _num(n.get("legacyResourceId"))
            old = stored.get(oid, {})
            fl = []
            for f in n.get("fulfillments") or []:
                fid = _num(f.get("legacyResourceId"))
                nf = normalise_fulfillment(f, details.get(fid))
                if fid not in details and reuse_detail(f, old.get(fid)):
                    nf.update({k: old[fid][k] for k in ("events", "items", "events_complete") if k in old[fid]})
                fl.append(nf)
            rows.append(order_row(store, n, fl, fetched_at))
            if n.get("updatedAt") and (max_updated is None or n["updatedAt"] > max_updated):
                max_updated = n["updatedAt"]
        for i in range(0, len(rows), 100):
            c.upsert("shopify_orders", rows[i:i + 100], on_conflict="id")
        cursor = CURSOR_PREFIX + (max_updated or _iso(since + timedelta(minutes=OVERLAP_MINUTES)))
        c.update("sync_runs", [("id", f"eq.{run_id}")], {
            "status": "ok", "finished_at": _iso(datetime.now(timezone.utc)), "rows_read": len(nodes),
            "rows_written": len(rows), "cursor": cursor})
        return {"store": store, "state": "ok", "mode": "first load" if first else mode, "orders": len(rows),
                "fulfillments_detailed": len(details)}
    except Exception as e:  # noqa: BLE001 — recorded on the run; never stops the other store
        msg = getattr(e, "message", None) or str(e)
        log.warning("shopify sync %s failed: %s", store, msg)
        try:
            c.update("sync_runs", [("id", f"eq.{run_id}")], {
                "status": "failed", "finished_at": _iso(datetime.now(timezone.utc)), "error": msg[:1000]})
        except SupabaseError:
            pass
        return {"store": store, "state": "failed", "error": msg[:300]}


def sync_all(triggered_by: str) -> list[dict[str, Any]]:
    """Every store with keys in .env. Never raises: each store's result (ok / failed / not_configured) is returned."""
    def one(store: str) -> dict[str, Any]:
        try:
            return sync_store(store, triggered_by)
        except SupabaseError as e:
            return {"store": store, "state": "failed", "error": e.message[:300]}

    # the stores are independent (own Shopify keys, own rows, own run lock): read them at the same time
    with ThreadPoolExecutor(max_workers=len(STORE_BRAND) or 1, thread_name_prefix="shopify-read") as pool:
        return list(pool.map(one, STORE_BRAND))
