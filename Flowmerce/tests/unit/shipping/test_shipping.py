"""Shipping module tests. Written with unittest so they run with the standard library
(`python -m unittest discover -s tests/unit/shipping -t .`) and are also collected by pytest.

No network: Supabase is replaced by httpx.MockTransport. These tests prove the module's own logic
(honest labels, safe query building, error handling, CSV safety); they do NOT prove the live data is
accurate. That is checked against the real database with db/central/110_validate.sql."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import httpx

from flowmerce.modules.shipping import rules, service
from flowmerce.modules.shipping.config import ShippingConfig
from flowmerce.modules.shipping.supabase import SupabaseClient, SupabaseError, set_client

CFG = ShippingConfig(url="https://example.supabase.co", key="test-key", schema="ops", timeout=5,
                     refresh_minutes=0)


class Recorder:
    """A fake PostgREST: answers by path, records every request."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.replace("/rest/v1/", "")
        answer = self.routes.get(path, [])
        if callable(answer):
            return answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer, headers={"content-range": f"0-0/{len(answer) if isinstance(answer, list) else 1}"})

    def params(self, i: int = -1) -> list[tuple[str, str]]:
        return parse_qsl(self.requests[i].url.query.decode())


def use(routes: dict[str, object]) -> Recorder:
    rec = Recorder(routes)
    set_client(SupabaseClient(CFG, transport=httpx.MockTransport(rec)))
    return rec


class RulesTest(unittest.TestCase):
    def test_shopify_delivered_is_not_carrier_confirmed(self):
        v = rules.status_view("delivered", "shopify", False)
        self.assertEqual(v["label"], "Delivered")
        self.assertEqual(v["qualifier"], "not carrier-confirmed")
        self.assertFalse(v["confirmed"])

    def test_confirmed_delivery(self):
        v = rules.status_view("delivered", "aggregator", True)
        self.assertTrue(v["confirmed"])
        self.assertEqual(v["qualifier"], "")

    def test_pending_is_called_unverified_never_in_transit(self):
        v = rules.status_view("pending", "shopify", False)
        self.assertEqual(v["label"], "Unverified")
        self.assertEqual(v["tone"], "neutral")

    def test_unknown_status_word_is_shown_as_is(self):
        self.assertEqual(rules.status_view("weird_word", None, None)["label"], "Weird word")

    def test_freshness_levels(self):
        now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        iso = lambda h: (now - timedelta(hours=h)).isoformat()  # noqa: E731
        self.assertEqual(rules.freshness(iso(0.5), "ok", now)["level"], "ok")
        self.assertEqual(rules.freshness(iso(5), "ok", now)["level"], "warn")
        self.assertEqual(rules.freshness(iso(30), "ok", now)["level"], "crit")
        self.assertEqual(rules.freshness(iso(0.5), "failed", now)["level"], "crit")
        self.assertEqual(rules.freshness(None, None, now)["level"], "none")

    def test_search_filter_strips_postgrest_syntax(self):
        self.assertEqual(rules.search_filter("#RBP7752"), "(order_name.ilike.*RBP7752*,tracking_number.ilike.*RBP7752*)")
        f = rules.search_filter("a,b).or(x.eq.1")
        self.assertNotIn(",b", f or "")
        self.assertNotIn(")", (f or "")[1:-1])
        self.assertIsNone(rules.search_filter("a"))

    def test_clamp_int(self):
        self.assertEqual(rules.clamp_int("abc", 25, 1, 200), 25)
        self.assertEqual(rules.clamp_int("9999", 25, 1, 200), 200)
        self.assertEqual(rules.clamp_int("0", 1, 1, 10), 1)


class ClientErrorTest(unittest.TestCase):
    def tearDown(self):
        set_client(None)

    def test_not_configured(self):
        set_client(SupabaseClient(ShippingConfig("", "", "ops", 5, 0)))
        res = service.summary("all")
        self.assertEqual(res["source"]["state"], "not_configured")
        self.assertIsNone(res["totals"])

    def test_schema_not_exposed(self):
        use({"shipping_summary": httpx.Response(406, json={"code": "PGRST106", "message": "x"})})
        self.assertEqual(service.summary("all")["source"]["state"], "schema_missing")

    def test_permission_denied(self):
        use({"shipment_list": httpx.Response(401, json={"message": "bad jwt"})})
        with self.assertRaises(SupabaseError) as cm:
            service.list_shipments()
        self.assertEqual(cm.exception.state, "permission_denied")

    def test_error_text_never_contains_key_or_url(self):
        use({"shipment_list": httpx.Response(500, json={"message": "boom"})})
        with self.assertRaises(SupabaseError) as cm:
            service.list_shipments()
        self.assertNotIn("test-key", cm.exception.message)
        self.assertNotIn("example.supabase.co", cm.exception.message)

    def test_reads_retry_then_succeed(self):
        calls = {"n": 0}

        def flaky(_req):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=[], headers={"content-range": "*/0"})
        use({"shipment_list": flaky})
        self.assertEqual(service.list_shipments()["total"], 0)
        self.assertEqual(calls["n"], 2)

    def test_schema_headers_and_key_sent(self):
        rec = use({"shipment_list": []})
        service.list_shipments()
        r = rec.requests[-1]
        self.assertEqual(r.headers["Accept-Profile"], "ops")
        self.assertEqual(r.headers["apikey"], "test-key")


class ServiceTest(unittest.TestCase):
    def tearDown(self):
        set_client(None)

    def test_list_builds_safe_filters(self):
        rec = use({"shipment_list": []})
        service.list_shipments(brand="ridhi", q="RBP77", status="exception", band="red", carrier="dhl",
                               flag="no_movement", sort="days", direction="asc", page="2", size="10")
        p = rec.params()
        self.assertIn(("store", "eq.RBP"), p)
        self.assertIn(("active", "is.true"), p)
        self.assertIn(("status", "eq.exception"), p)
        self.assertIn(("age_band", "eq.red"), p)
        self.assertIn(("carrier_id", "eq.dhl"), p)
        self.assertIn(("no_movement", "is.true"), p)
        self.assertIn(("order", "days_since_dispatch.asc.nullslast,tracking_id.asc"), p)
        self.assertEqual(rec.requests[-1].headers["Range"], "10-19")

    def test_list_ignores_unknown_values(self):
        rec = use({"shipment_list": []})
        service.list_shipments(status="drop table", band="purple", carrier="DHL; --", sort="evil")
        p = dict(rec.params())
        self.assertNotIn("status", p)
        self.assertNotIn("age_band", p)
        self.assertNotIn("carrier_id", p)
        self.assertTrue(p["order"].startswith("days_since_dispatch."))

    def test_rows_get_honest_status_view(self):
        use({"shipment_list": [{"tracking_id": "x", "status": "delivered", "source": "shopify",
                                "delivery_confirmed": False}]})
        row = service.list_shipments()["rows"][0]
        self.assertEqual(row["status_view"]["qualifier"], "not carrier-confirmed")

    def test_summary_totals_and_problem_order(self):
        use({
            "shipping_summary": [{"store": "RBP", "open_tracking": 10, "in_transit": 3, "out_for_delivery": 1,
                                  "delivered_30d": 5, "delivered_confirmed_30d": 0, "exceptions": 2, "unverified": 4}],
            "feed_freshness": [{"source": "shopify", "kind": "import", "store": None,
                                "last_ok_at": datetime.now(timezone.utc).isoformat(), "last_status": "ok"}],
            "diagnostics_summary": [{"store": "RBP", "problem": "kind_unconfirmed", "severity": "amber", "n": 50},
                                    {"store": "RBP", "problem": "no_movement", "severity": "red", "n": 3}],
        })
        s = service.summary("all")
        self.assertEqual(s["totals"]["open_tracking"], 10)
        self.assertEqual(s["problems"][0]["problem"], "no_movement")     # urgent first
        self.assertEqual(s["freshness"][0]["view"]["level"], "ok")

    def test_detail_rejects_non_uuid(self):
        use({})
        self.assertIsNone(service.shipment_detail("1 or 1=1"))

    def test_mark_validation(self):
        use({})
        with self.assertRaises(SupabaseError):
            service.set_mark("not-a-uuid", "lost", None, "a@b")
        with self.assertRaises(SupabaseError):
            service.set_mark("00000000-0000-0000-0000-000000000000", "stolen", None, "a@b")
        with self.assertRaises(SupabaseError):
            service.set_mark("00000000-0000-0000-0000-000000000000", None, "  ", "a@b")

    def test_mark_calls_rpc(self):
        rec = use({"rpc/set_team_mark": {"ok": True}})
        service.set_mark("00000000-0000-0000-0000-000000000000", "lost", "box empty", "ops@x")
        body = json.loads(rec.requests[-1].content)
        self.assertEqual(body, {"p_tracking_id": "00000000-0000-0000-0000-000000000000", "p_mark": "lost",
                                "p_note": "box empty", "p_by": "ops@x"})

    def test_failed_refresh_is_recorded(self):
        rec = use({"rpc/refresh_from_shopify_orders": httpx.Response(500, json={"message": "boom"}),
                   "sync_runs": httpx.Response(201)})
        with self.assertRaises(SupabaseError):
            service.refresh("ops@x", read_shopify=False)
        last = rec.requests[-1]
        self.assertTrue(last.url.path.endswith("/sync_runs"))
        body = json.loads(last.content)
        self.assertEqual((body["status"], body["source"], body["kind"]), ("failed", "shopify", "import"))

    def test_refresh_calls_the_shopify_orders_function_for_all_stores(self):
        rec = use({"rpc/refresh_from_shopify_orders": {"run_id": 1, "fulfillments_incomplete": 3}})
        res = service.refresh("ops@x", read_shopify=False)
        self.assertTrue(rec.requests[-1].url.path.endswith("/rpc/refresh_from_shopify_orders"))
        self.assertEqual(json.loads(rec.requests[-1].content), {})
        self.assertEqual(res["result"]["fulfillments_incomplete"], 3)

    def test_refresh_is_not_retried(self):
        calls = {"n": 0}

        def fail(_r):
            calls["n"] += 1
            return httpx.Response(503)
        use({"rpc/refresh_from_shopify_orders": fail, "sync_runs": httpx.Response(201)})
        with self.assertRaises(SupabaseError):
            service.refresh("x", read_shopify=False)
        self.assertEqual(calls["n"], 1)

    def test_csv_neutralises_formulas(self):
        use({"shipment_list": [{"order_name": "=HYPERLINK(\"x\")", "tracking_number": "+123", "carrier_name": "DHL"}]})
        text = service.export_csv()
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+123", text)


class HomeSnapshotTest(unittest.TestCase):
    """Shipping figures on the Home page: per brand, never added across brands by mistake, never an error."""

    SUMMARY = [{"store": "RBP", "open_tracking": 10, "in_transit": 3, "out_for_delivery": 1, "delivered_30d": 20, "exceptions": 2, "unverified": 4},
               {"store": "CPC", "open_tracking": 5, "in_transit": 1, "out_for_delivery": 0, "delivered_30d": 9, "exceptions": 1, "unverified": 2}]

    def test_one_brand_only_counts_its_store(self):
        rec = use({"shipping_summary": self.SUMMARY, "shipment_list": [
            {"order_name": "#R1", "store": "RBP", "carrier_name": None, "days_since_dispatch": 12, "last_scan_place": "X", "tracking_id": "t1"}]})
        s = service.home_snapshot(["ridhi"])
        self.assertEqual(s["all"]["active"], 10)
        self.assertEqual(s["all"]["inTransit"], 4)
        self.assertEqual(s["all"]["problems"], 2)
        self.assertEqual(list(s["byBrand"]), ["ridhi"])
        self.assertEqual(s["all"]["top"][0], {"order": "#R1", "brand": "ridhi", "carrier": "Unknown", "days": 12, "place": "X", "trackingId": "t1"})
        self.assertIn(("store", "in.(RBP)"), rec.params())

    def test_both_brands_kept_separate_in_by_brand(self):
        use({"shipping_summary": self.SUMMARY, "shipment_list": []})
        s = service.home_snapshot(["ridhi", "cpc"])
        self.assertEqual(s["all"]["problems"], 3)
        self.assertEqual((s["byBrand"]["ridhi"]["problems"], s["byBrand"]["cpc"]["problems"]), (2, 1))

    def test_supabase_down_gives_none_not_an_error(self):
        use({"shipping_summary": httpx.Response(500, json={"message": "boom"})})
        self.assertIsNone(service.home_snapshot(["ridhi"]))
        self.assertIsNone(service.home_snapshot([]))


class ShopifySourceTest(unittest.TestCase):
    """Reading Shopify directly: normalising, cursors, and one store's run against fakes (no network)."""

    def setUp(self):
        from flowmerce.modules.shipping import shopify_source
        self.ss = shopify_source

    def test_normalise_fulfillment_with_events_and_items(self):
        f = {"legacyResourceId": "21", "status": "SUCCESS", "displayStatus": "DELIVERED", "createdAt": "2026-11-01T00:00:00Z",
             "updatedAt": "2026-11-05T00:00:00Z", "deliveredAt": "2026-11-04T10:00:00Z", "estimatedDeliveryAt": None,
             "inTransitAt": "2026-11-02T00:00:00Z", "service": {"handle": "manual"},
             "trackingInfo": [{"company": "DHL Express", "number": " 123 ", "url": "u"}]}
        d = {"events": {"pageInfo": {"hasNextPage": False}, "nodes": [
                {"id": "gid://shopify/FulfillmentEvent/9", "status": "DELIVERED", "happenedAt": "2026-11-04T10:00:00Z",
                 "message": None, "city": "Austin", "province": "TX", "country": "US"},
                {"id": "gid://shopify/FulfillmentEvent/8", "status": "IN_TRANSIT", "happenedAt": None}]},
             "fulfillmentLineItems": {"nodes": [{"quantity": 2, "lineItem": {"id": "gid://shopify/LineItem/77"}}]}}
        out = self.ss.normalise_fulfillment(f, d)
        self.assertEqual((out["id"], out["status"], out["display_status"]), (21, "success", "DELIVERED"))
        self.assertEqual(out["tracking"][0]["number"], "123")
        self.assertEqual(out["items"], [{"item_id": 77, "qty": 2}])
        self.assertEqual([e["id"] for e in out["events"]], [9])          # an event without a time is dropped
        self.assertTrue(out["events_complete"])
        self.assertNotIn("customer", json.dumps(out).lower())

    def test_reuse_only_unchanged_finished_parcels(self):
        old = {"updated_at": "T1", "display_status": "DELIVERED", "events": []}
        self.assertTrue(self.ss.reuse_detail({"updatedAt": "T1"}, old))
        self.assertFalse(self.ss.reuse_detail({"updatedAt": "T2"}, old))
        self.assertFalse(self.ss.reuse_detail({"updatedAt": "T1"}, {**old, "display_status": "IN_TRANSIT"}))
        self.assertFalse(self.ss.reuse_detail({"updatedAt": "T1"}, None))

    def test_cursor_window(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        since, first = self.ss.since_from_cursor(None, now)
        self.assertTrue(first)
        self.assertEqual(since, now - timedelta(days=60))
        since, first = self.ss.since_from_cursor("orders_updated_at:2026-11-17T11:00:00Z", now)
        self.assertFalse(first)
        self.assertEqual(since, datetime(2026, 11, 17, 10, 50, tzinfo=timezone.utc))
        self.assertTrue(self.ss.since_from_cursor("hub_run:5", now)[1])

    def _supabase(self, run_post=None):
        def sync_runs(req):
            if req.method == "POST":
                return run_post or httpx.Response(201, json=[{"id": 7}])
            if req.method == "PATCH":
                return httpx.Response(204)
            return httpx.Response(200, json=[])                       # no previous cursor
        return use({"sync_runs": sync_runs, "shipments": [], "shopify_orders":
                    lambda r: httpx.Response(201) if r.method == "POST" else httpx.Response(200, json=[])})

    def _fake_shopify(self):
        order = {"legacyResourceId": "1001", "name": "#R1001", "createdAt": "2026-11-10T00:00:00Z",
                 "updatedAt": "2026-11-16T08:00:00Z", "cancelledAt": None, "displayFulfillmentStatus": "FULFILLED",
                 "fulfillments": [{"legacyResourceId": "55", "status": "SUCCESS", "displayStatus": "IN_TRANSIT",
                                   "createdAt": "2026-11-11T00:00:00Z", "updatedAt": "2026-11-16T08:00:00Z",
                                   "trackingInfo": [{"company": "USPS", "number": "9400", "url": None}]}]}

        def gql(query, variables=None):
            if "orders(first: 250" in query:
                return {"orders": {"nodes": [{"id": "gid://shopify/Order/1001"}],
                                   "pageInfo": {"hasNextPage": False, "endCursor": None}}}
            if "... on Order" in query:
                return {"nodes": [order]}
            if "... on Fulfillment" in query:
                return {"nodes": [{"legacyResourceId": "55", "events": {"pageInfo": {"hasNextPage": False}, "nodes": [
                    {"id": "gid://shopify/FulfillmentEvent/1", "status": "IN_TRANSIT", "happenedAt": "2026-11-12T00:00:00Z"}]},
                    "fulfillmentLineItems": {"nodes": []}}]}
            raise AssertionError(query)
        return gql

    def test_store_run_writes_snapshot_and_cursor(self):
        rec = self._supabase()
        res = self.ss.sync_store("RBP", "test", gql=self._fake_shopify(),
                                 now=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertEqual((res["state"], res["orders"]), ("ok", 1))
        up = next(r for r in rec.requests if r.method == "POST" and r.url.path.endswith("/shopify_orders"))
        self.assertIn(("on_conflict", "id"), parse_qsl(up.url.query.decode()))
        row = json.loads(up.content)[0]
        self.assertEqual((row["id"], row["store"]), (1001, "RBP"))
        self.assertEqual(row["fulfillments"][0]["events"][0]["status"], "IN_TRANSIT")
        done = json.loads([r for r in rec.requests if r.method == "PATCH"][-1].content)
        self.assertEqual(done["status"], "ok")
        self.assertEqual(done["cursor"], "orders_updated_at:2026-11-16T08:00:00Z")
        for r in rec.requests:                                         # keys never travel to Supabase
            self.assertNotIn(b"client_secret", r.content or b"")
            self.assertNotIn(b"shpat_", r.content or b"")

    def test_store_failure_is_recorded_and_contained(self):
        rec = self._supabase()

        def broken(query, variables=None):
            raise RuntimeError("Shopify refused the client id/secret for CPC (400).")
        res = self.ss.sync_store("CPC", "test", gql=broken)
        self.assertEqual(res["state"], "failed")
        done = json.loads([r for r in rec.requests if r.method == "PATCH"][-1].content)
        self.assertEqual(done["status"], "failed")
        self.assertIn("refused", done["error"])

    def test_second_run_at_the_same_time_is_skipped(self):
        self._supabase(run_post=httpx.Response(409, json={"code": "23505", "message": "duplicate key"}))
        res = self.ss.sync_store("RBP", "test", gql=self._fake_shopify())
        self.assertEqual(res["state"], "already_running")

    def test_refresh_reads_shopify_first_then_merges(self):
        from unittest import mock
        rec = use({"rpc/refresh_from_shopify_orders": {"run_id": 1}})
        with mock.patch("flowmerce.modules.shipping.shopify_source.sync_all",
                        return_value=[{"store": "RBP", "state": "ok"}]) as s:
            res = service.refresh("ops@x")
        s.assert_called_once_with("ops@x")
        self.assertEqual(res["shopify"], [{"store": "RBP", "state": "ok"}])
        self.assertTrue(rec.requests[-1].url.path.endswith("/rpc/refresh_from_shopify_orders"))


class SqlFilesTest(unittest.TestCase):
    """Static checks on the SQL (no database needed)."""

    def setUp(self):
        from pathlib import Path
        self.dir = Path(__file__).resolve().parents[3] / "db" / "central"

    def test_no_sql_writes_to_public_tables(self):
        import re
        for f in self.dir.glob("*.sql"):
            text = f.read_text(encoding="utf-8").lower()
            bad = re.findall(r"(insert\s+into|update|delete\s+from|truncate|drop\s+table)\s+public\.", text)
            self.assertEqual(bad, [], f"{f.name} writes to public.*")

    def test_status_map_covers_every_raw_word_seen_live(self):
        seed = (self.dir / "090_seed.sql").read_text(encoding="utf-8")
        for word in ("DELIVERED", "FULFILLED", "CONFIRMED", "IN_TRANSIT", "NOT_DELIVERED", "DELAYED",
                     "ATTEMPTED_DELIVERY", "OUT_FOR_DELIVERY"):
            self.assertIn(f"('shopify','*','{word}'", seed)

    def test_exceptions_not_hidden_as_fulfilled(self):
        seed = (self.dir / "090_seed.sql").read_text(encoding="utf-8")
        for word in ("NOT_DELIVERED", "DELAYED", "ATTEMPTED_DELIVERY"):
            line = next(l for l in seed.splitlines() if f"'{word}'" in l and "'shopify'" in l)
            self.assertIn("'exception'", line)

    def test_refresh_reads_the_hub_tables_not_the_old_tracker(self):
        import re
        raw = (self.dir / "105_refresh_from_shopify_orders.sql").read_text(encoding="utf-8").lower()
        text = re.sub(r"--[^\n]*", "", raw)                       # code only, not comments
        self.assertIn("from public.orders", text)
        self.assertIn("p.raw->'fulfillments'", text)
        for gone in ("public.order_checks", "public.manual_status", "raw_tracking_status", "last_scan_description"):
            self.assertNotIn(gone, text)
        self.assertFalse((self.dir / "100_tracker_refresh.sql").exists())

    def test_setup_file_is_built_from_105(self):
        setup = (self.dir / "supabase_setup.sql").read_text(encoding="utf-8")
        self.assertIn("create or replace function ops.refresh_from_shopify_orders", setup)
        self.assertIn("create or replace function ops.set_team_mark", setup)
        self.assertNotIn("create or replace function ops.refresh_from_tracker", setup)

    def test_shopify_never_confirms_delivery(self):
        text = (self.dir / "105_refresh_from_shopify_orders.sql").read_text(encoding="utf-8").lower()
        self.assertNotRegex(text, r"delivery_confirmed\s*=\s*true")
        self.assertIn("false,                                            -- shopify's word never confirms", text)

    def test_status_words_seen_in_public_orders_are_mapped(self):
        words = ((self.dir / "090_seed.sql").read_text(encoding="utf-8")
                 + (self.dir / "105_refresh_from_shopify_orders.sql").read_text(encoding="utf-8"))
        for word in ("DELIVERED", "IN_TRANSIT", "CONFIRMED", "FAILURE", "DELAYED", "OUT_FOR_DELIVERY",
                     "ATTEMPTED_DELIVERY", "RETURNING_TO_SENDER"):
            self.assertRegex(words, rf"\('shopify','\*','{word}',")

    def test_every_carrier_spelling_seen_live_has_an_alias(self):
        seed = (self.dir / "090_seed.sql").read_text(encoding="utf-8").lower()
        for alias in ("dhl express", "amazon logistics", "amazon logistics us", "fedex", "usps", "ups",
                      "other", "amazon fulfillment", "dhl ecommerce"):
            self.assertIn(f"('{alias}',", seed)


if __name__ == "__main__":
    unittest.main()
