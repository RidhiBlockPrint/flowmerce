"""The Shipping page figures (board.py), from synthetic flow_board rows. No network: the snapshot is built by hand."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from flowmerce.modules.seo.db import open_db
from flowmerce.modules.shipping import board

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def row(**kw):
    base = {"row_kind": "tracking", "row_id": kw.get("row_id", kw.get("tracking_number", "x")), "tracking_id": None,
            "store": "RBP", "order_id": 1, "order_name": "#R1", "placed_at": ago(12), "kind": "india",
            "carrier_name": "DHL Express", "tracking_number": "T1", "track_url": "u", "status": "in_transit",
            "raw_status": "IN_TRANSIT", "source": "shopify", "shipped_at": ago(10), "last_scan_at": ago(1),
            "last_scan_place": "X", "last_scan_text": "Departed", "delivered_at": None, "eta": None,
            "last_check_ok_at": ago(0.1), "team_mark": None, "team_mark_at": None, "open_exceptions": 0,
            "total": 50.0, "currency": "USD", "financial_status": "PAID", "fulfillment_status": "FULFILLED",
            "cancelled_at": None, "ship_city": "Austin", "ship_state": "TX", "note_done": False}
    base.update(kw)
    return base


def snap(rows, feeds=None):
    return board.Snapshot(rows, feeds if feeds is not None else
                          [{"source": "shopify", "kind": "import", "store": None, "last_ok_at": ago(0.05), "last_status": "ok"}], NOW)


class BoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        open_db(":memory:")

    def ds(self, rows, brand="all", feeds=None):
        return board.build(brand, now=NOW, snap=snap(rows, feeds))

    def test_aging_clock_and_categories(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", order_name="#1", shipped_at=ago(10)),                 # dispatched 10 d -> red
            row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(5)),                  # yellow
            row(row_id="c", tracking_number="C", order_name="#3", shipped_at=ago(1)),                  # on track
            row(row_id="o", row_kind="order", order_name="#4", placed_at=ago(3), tracking_number=None,  # not dispatched 3 d -> grey
                carrier_name=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="d", tracking_number="D", order_name="#5", status="delivered", delivered_at=ago(2)),
        ])
        cats = {r["order_number"]: r["cat"] for r in d.rows}
        self.assertEqual(cats, {"#1": "red", "#2": "yellow", "#3": "on_track", "#4": "grey", "#5": "delivered"})
        s = board.summary(d)
        self.assertEqual(s["activeTotal"], 4)
        self.assertEqual((s["stage"]["preDispatch"], s["stage"]["dispatched"], s["delivered"]), (1, 3, 1))
        self.assertIn("1 shipment(s) are 9+ days", s["banner"])

    def test_amazon_without_updates_is_unconfirmed_never_critical(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", carrier_name="Amazon Logistics US", status="pending", last_scan_at=None, shipped_at=ago(20)),
            row(row_id="b", tracking_number="B", order_name="#2", carrier_name="Amazon Logistics US", status="in_transit", shipped_at=ago(20)),
        ])
        by = {r["tracking_number"]: r for r in d.rows}
        self.assertEqual(by["A"]["cat"], "unconfirmed")
        self.assertFalse(by["A"]["noMove"])
        self.assertEqual(by["B"]["cat"], "red")                      # Amazon WITH carrier updates follows the rules
        self.assertEqual(board.verify_report(d)["total"], 1)

    def test_named_carrier_never_scanned_is_unconfirmed_not_critical(self):
        d = self.ds([
            # USPS number Shopify never got a scan for (e.g. # RBP7437): 26 days, no evidence of a delay
            row(row_id="a", tracking_number="U26", carrier_name="USPS", status="pending", last_scan_at=None, shipped_at=ago(26)),
            # shipped yesterday: no first scan yet is normal, the clock runs
            row(row_id="b", tracking_number="U1", order_name="#2", carrier_name="USPS", status="pending", last_scan_at=None, shipped_at=ago(1)),
            # USPS with real scans, 20 days: the normal rules (critical)
            row(row_id="c", tracking_number="U20", order_name="#3", carrier_name="USPS", status="in_transit", last_scan_at=ago(15), shipped_at=ago(20)),
        ])
        by = {r["tracking_number"]: r for r in d.rows}
        self.assertEqual((by["U26"]["cat"], by["U26"]["unconfirmed"], by["U26"]["noMove"]), ("unconfirmed", True, False))
        self.assertEqual((by["U1"]["cat"], by["U1"]["unconfirmed"]), ("on_track", False))
        self.assertEqual((by["U20"]["cat"], by["U20"]["unconfirmed"]), ("red", False))
        self.assertEqual(board.verify_report(d)["total"], 1)

    def test_hub_only_failure_is_unconfirmed_not_critical(self):
        d = self.ds([
            # #4434: older than 60 days, hub copy says only "failure" (DHL had delivered it): hand check, not critical
            row(row_id="a", tracking_number="H", status="exception", raw_status="failure", shipped_at=ago(41),
                last_scan_at=ago(23), last_scan_text="Shopify shipment status: failure"),
            # a failure WITH carrier events (direct Shopify read) follows the normal rules
            row(row_id="b", tracking_number="E", order_name="#2", status="exception", raw_status="FAILURE",
                shipped_at=ago(20), last_scan_at=ago(2), last_scan_text="Delivery attempted"),
            # the team checked DHL and marked the hub parcel delivered
            row(row_id="c", tracking_number="M", order_name="#3", status="exception", raw_status="failure", shipped_at=ago(41),
                last_scan_at=ago(23), last_scan_text="Shopify shipment status: failure", team_mark="delivered"),
        ])
        by = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual((by["H"]["cat"], by["H"]["unconfirmed"], by["H"]["exc"], by["H"]["noMove"]), ("unconfirmed", True, "", False))
        self.assertEqual((by["E"]["cat"], by["E"]["exc"]), ("red", "failure"))
        self.assertEqual(by["M"]["cat"], "delivered")
        self.assertEqual([x["order"] for x in board.exception_rows(d) if x["type"] == "carrier_exception"], ["#2"])
        self.assertEqual(board.summary(d)["critical"], 1)

    def test_team_mark_applies_to_unconfirmed_only(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", carrier_name="Unknown carrier", status="pending", last_scan_at=None, team_mark="lost"),
            row(row_id="b", tracking_number="B", order_name="#2", team_mark="lost"),
        ])
        by = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual((by["A"]["cat"], by["A"]["resolved"]["outcome"]), ("lost", "lost"))   # lost: moved to Resolved
        self.assertNotIn(by["A"], d.rows)
        self.assertEqual(by["B"]["cat"], "red")
        self.assertEqual(board.verify_report(d)["team"]["lost"], 1)

    def test_cancelled_and_refunded_are_left_out(self):
        d = self.ds([row(row_id="a", tracking_number="A", cancelled_at=ago(1)),
                     row(row_id="b", tracking_number="B", order_name="#2", financial_status="REFUNDED"),
                     row(row_id="c", tracking_number="C", order_name="#3")])
        self.assertEqual([r["order_number"] for r in d.rows], ["#3"])
        self.assertEqual(board.order_detail(d, "#R1")["excluded"], "cancelled")

    def test_no_movement_and_exceptions(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", last_scan_at=ago(6), last_scan_text="Arrived at hub"),
            row(row_id="b", tracking_number="B", order_name="#2", status="exception", raw_status="FAILURE", open_exceptions=1),
            row(row_id="s", row_kind="shipment", tracking_number=None, order_name="#3", status="pending", last_scan_at=None),
            row(row_id="c", tracking_number="DUP", order_name="#4"), row(row_id="e", tracking_number="DUP", order_name="#5"),
            row(row_id="f", tracking_number="F", order_name="#6", shipped_at=ago(3), eta=(NOW - timedelta(days=2)).date().isoformat()),
        ])
        types = {(x["order"], x["type"]) for x in board.exception_rows(d)}
        self.assertIn(("#R1", "stuck"), types)
        self.assertIn(("#2", "carrier_exception"), types)
        self.assertIn(("#3", "missing_tracking"), types)
        self.assertIn(("#4", "duplicate_tracking"), types)
        self.assertIn(("#6", "overdue"), types)
        self.assertEqual(board.kpis(d)[7]["value"], 1)           # carrier exceptions
        self.assertEqual(board.kpis(d)[8]["value"], 1)           # no movement

    def test_note_says_done_but_not_fulfilled(self):
        d = self.ds([
            row(row_id="o1", row_kind="order", order_name="#9", placed_at=ago(11), note_done=True, fulfillment_status="UNFULFILLED",
                tracking_number=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="o2", row_kind="order", order_name="#10", placed_at=ago(3), note_done=True, fulfillment_status="UNFULFILLED",
                tracking_number=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="a", tracking_number="A", note_done=True),   # fulfilled: fine
        ])
        m = board.mcf_report(d)
        self.assertEqual([(r["order"], r["level"]) for r in m["rows"]], [("#9", "critical")])

    def test_value_at_risk_counts_each_order_once(self):
        d = self.ds([row(row_id="a", tracking_number="A", total=40.0), row(row_id="b", tracking_number="B", total=40.0),
                     row(row_id="c", tracking_number="C", order_name="#2", total=10.0)])
        self.assertEqual(board.value_at_risk(d), {"available": True, "orders": 2, "total": 50.0, "currency": "USD", "note": ""})

    def test_brands_are_kept_apart(self):
        rows = [row(row_id="a", tracking_number="A"), row(row_id="b", tracking_number="B", store="CPC", order_name="#7")]
        self.assertEqual([r["brand"] for r in self.ds(rows, "ridhi").rows], ["ridhi"])
        self.assertEqual([r["brand"] for r in self.ds(rows, "cpc").rows], ["cpc"])
        self.assertEqual(len(self.ds(rows, "all").rows), 2)

    def test_delivery_performance_on_time_uses_promised_date_only(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", status="delivered", shipped_at=ago(6), delivered_at=ago(2),
                eta=(NOW - timedelta(days=3)).date().isoformat()),                     # late
            row(row_id="b", tracking_number="B", order_name="#2", status="delivered", shipped_at=ago(6), delivered_at=ago(4),
                eta=(NOW - timedelta(days=3)).date().isoformat()),                     # on time
            row(row_id="c", tracking_number="C", order_name="#3", status="delivered", shipped_at=ago(5), delivered_at=ago(3)),  # no ETA
        ])
        p = board.delivery_report(d, 30)
        self.assertEqual((p["delivered"], p["onTimePct"], p["withPromisedDate"]), (3, 50, 2))
        self.assertEqual(p["byRegion"][0]["region"], "TX")

    def test_list_filters_and_sort(self):
        d = self.ds([row(row_id="a", tracking_number="A", shipped_at=ago(10)),
                     row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(1), status="exception", raw_status="DELAYED"),
                     row(row_id="c", tracking_number="C", order_name="#3", shipped_at=ago(5))])
        out = board.list_rows(d, cat="")
        self.assertEqual([r["order"] for r in out["rows"]], ["#2", "#R1", "#3"])     # exception first, then red
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        self.assertEqual(board.list_rows(d, q="c")["rows"][0]["order"], "#3")

    def test_order_marks_and_notes_are_saved_locally(self):
        d = self.ds([row(row_id="a", tracking_number="A", order_id=4242, order_name="#M1")])
        r = board.annotate(d, "#M1", "flag", "", "Ops")
        self.assertTrue(r["annotation"]["flagged"])
        r = board.annotate(d, "#M1", "note", "Called the carrier", "Ops")
        self.assertEqual(r["annotation"]["notes"][0]["text"], "Called the carrier")
        self.assertEqual(board.list_rows(d, cat="flagged")["total"], 1)
        with self.assertRaises(Exception):
            board.annotate(d, "#M1", "note", "   ", "Ops")

    def test_team_outcome_takes_an_order_out_of_critical(self):
        order = row(row_id="o", row_kind="order", order_id=5151, order_name="#U1", tracking_number=None, carrier_name=None,
                    status=None, raw_status=None, shipped_at=None, last_scan_at=None, placed_at=ago(30),
                    fulfillment_status="UNFULFILLED")
        d = self.ds([order])
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        r = board.annotate(d, "#U1", "outcome", "Refunded", "Ops")
        self.assertEqual((r["annotation"]["outcome"], r["annotation"]["outcomeBy"]), ("refunded", "Ops"))
        self.assertIn("Resolved as refunded", r["packages"][0]["action"])
        self.assertEqual(board.list_rows(d, cat="red")["total"], 0)               # gone from Critical
        self.assertEqual(next(k for k in board.kpis(d) if k["key"] == "")["value"], 0)   # and from the active total
        res = board.list_rows(d, cat="resolved")
        self.assertEqual((res["total"], res["rows"][0]["cat"], res["rows"][0]["resolved"]["label"]), (1, "resolved", "Refunded"))
        d2 = self.ds([order])                                                      # a fresh read keeps it resolved
        self.assertEqual(board.list_rows(d2, cat="red")["total"], 0)
        board.annotate(d, "#U1", "clear_outcome", "", "Ops")                        # undo
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        with self.assertRaises(Exception):
            board.annotate(d, "#U1", "outcome", "sold", "Ops")

    def test_carrier_lost_or_returned_is_resolved(self):
        d = self.ds([
            row(row_id="a", tracking_number="DISP", order_id=61, order_name="#L1", shipped_at=ago(30), status="exception",
                raw_status="FAILURE", last_scan_at=ago(20),
                last_scan_text="An authorized request has been received to dispose of the shipment"),
            row(row_id="b", tracking_number="UNDL", order_id=62, order_name="#L2", shipped_at=ago(16), status="exception",
                raw_status="UNDELIVERABLE", last_scan_at=ago(10), last_scan_text="Delivery date is currently unavailable"),
            row(row_id="c", tracking_number="DLY", order_id=63, order_name="#L3", shipped_at=ago(20), status="exception",
                raw_status="DELAYED", last_scan_at=ago(10), last_scan_text="Package delayed in transit"),
        ])
        by = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual((by["DISP"]["resolved"]["outcome"], by["DISP"]["resolved"]["by"]), ("lost", "carrier"))
        self.assertEqual(by["UNDL"]["resolved"]["outcome"], "returned")
        self.assertIsNone(by["DLY"].get("resolved"))                              # a delay is still a delay
        self.assertEqual([r["tracking_number"] for r in d.rows], ["DLY"])
        self.assertEqual({e["tracking"] for e in board.exception_rows(d)}, {"DLY"})

    def test_import_preview_writes_nothing_and_checks_rows(self):
        d = self.ds([row(row_id="s", row_kind="shipment", tracking_number=None, order_name="#S1", status="pending", last_scan_at=None),
                     row(row_id="a", tracking_number="A", order_name="#S2")])
        res = board.preview_import(d, "order_number,tracking_number,carrier\n#S1,ABC123456,DHL Express\n#S2,ABC999999,DHL Express\n#S3,ABC123457,DHL Express\n#S1,12,DHL Express")
        self.assertEqual([r["outcome"] for r in res["rows"]], ["will_update", "skip_has_tracking", "error", "error"])
        self.assertTrue(res["previewOnly"])

    def test_amazon_rows(self):
        d = self.ds([
            row(row_id="9:1", row_kind="amazon", order_name="#A1", kind="mcf", carrier_name="USPS", tracking_number="9361289715570003153164",
                status="pending", source="amazon", shipped_at=ago(4), last_scan_at=None, last_scan_text="Amazon: Shipped by Amazon",
                fulfillment_status="UNFULFILLED", note_done=True, placed_at=ago(6), amazon_status="Shipped by Amazon"),
            row(row_id="9:2", row_kind="amazon", order_name="#A2", order_id=2, kind="mcf", carrier_name="Amazon Logistics US",
                tracking_number=None, status="pending", source="amazon", shipped_at=None, last_scan_at=None, placed_at=ago(11),
                fulfillment_status="UNFULFILLED", amazon_status="Amazon accepted"),
            row(row_id="o", row_kind="order", order_name="#A3", order_id=3, placed_at=ago(12), note_done=True, fulfillment_status="UNFULFILLED",
                tracking_number=None, carrier_name=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="t", tracking_number="DHLX", order_name="#A4", order_id=4, kind="mcf", carrier_name="DHL Express",
                status="pending", last_scan_at=None, shipped_at=ago(12)),
        ])
        by = {r["order_number"]: r for r in d.rows}
        self.assertEqual((by["#A1"]["stage"], by["#A1"]["cat"]), ("dispatched", "unconfirmed"))   # Amazon shipped: checked by hand
        self.assertEqual((by["#A2"]["stage"], by["#A2"]["cat"]), ("pre_dispatch", "red"))         # Amazon has not shipped in 11 days
        self.assertEqual(by["#A4"]["cat"], "unconfirmed")                                         # MCF parcel without carrier data
        exc = {(x["order"], x["type"]) for x in board.exception_rows(d)}
        self.assertIn(("#A1", "amazon_not_in_shopify"), exc)
        m = {r["order"]: r for r in board.mcf_report(d)["rows"]}
        self.assertEqual(m["#A1"]["amazon"], "Shipped by Amazon")
        self.assertIsNone(m["#A3"]["amazon"])
        self.assertIn("Mark it fulfilled in Shopify", board.order_detail(d, "#A1")["packages"][0]["action"])

    def test_reshipped_parcels_leave_the_delay_figures(self):
        rows = [
            # 1. stuck parcel of #R100, and a later replacement order #R200 that names it
            row(row_id="a", tracking_number="OLD1", order_id=100, order_name="#R100", shipment_id="s1", status="pending",
                last_scan_at=None, shipped_at=ago(30), placed_at=ago(31)),
            row(row_id="b", tracking_number="NEW1", order_id=200, order_name="#R200", shipment_id="s2", status="delivered",
                delivered_at=ago(1), shipped_at=ago(5), placed_at=ago(6)),
            # 2. same items sent again in the same order
            row(row_id="c", tracking_number="OLD2", order_id=300, order_name="#R300", shipment_id="s3", shipped_at=ago(20),
                last_scan_at=ago(15), last_scan_text="USPS Awaiting Item", placed_at=ago(21)),
            row(row_id="d", tracking_number="NEW2", order_id=300, order_name="#R300", shipment_id="s4", shipped_at=ago(4), placed_at=ago(21)),
            # 3. a split shipment (different items) is NOT a reship
            row(row_id="e", tracking_number="SPL1", order_id=400, order_name="#R400", shipment_id="s5", shipped_at=ago(20), placed_at=ago(21)),
            row(row_id="f", tracking_number="SPL2", order_id=400, order_name="#R400", shipment_id="s6", shipped_at=ago(4), placed_at=ago(21)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={"s1": {"1"}, "s2": {"9"}, "s3": {"7"}, "s4": {"7"}, "s5": {"5"}, "s6": {"6"}},
                            replacements=[{"id": 200, "name": "#R200", "store": "RBP", "placed_at": ago(6), "refs": ["100"]}],
                            reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        rr = {x["tracking"]: x for x in board.reshipped_report(d)["rows"]}
        self.assertEqual(set(rr), {"OLD1", "OLD2"})
        self.assertEqual((rr["OLD1"]["how"], rr["OLD1"]["newOrder"], rr["OLD1"]["newStatus"]), ("replacement_order", "#R200", "delivered"))
        self.assertEqual((rr["OLD2"]["how"], rr["OLD2"]["newTracking"]), ("sent_again", "NEW2"))
        active = {r["tracking_number"] for r in d.active}
        self.assertFalse({"OLD1", "OLD2"} & active)                 # out of every delay figure
        self.assertIn("SPL1", active)                                # split shipment stays
        self.assertEqual(board.list_rows(d, cat="reshipped")["total"], 2)
        self.assertEqual(board.list_rows(d, cat="reshipped")["rows"][0]["cat"], "reshipped")
        self.assertEqual(next(k for k in board.kpis(d) if k["key"] == "reshipped")["value"], 2)
        self.assertIsNotNone(board.order_detail(d, "#R100")["packages"][0]["reshipped"])

    def test_parcel_sent_after_the_replacement_is_not_replaced_by_it(self):
        rows = [row(row_id="a", tracking_number="LATE1", order_id=100, order_name="#R100", status="in_transit",
                    last_scan_at=ago(1), shipped_at=ago(3), placed_at=ago(31))]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[{"id": 200, "name": "#R200", "store": "RBP", "placed_at": ago(10), "refs": ["100"]}],
                            reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        self.assertEqual(board.reshipped_report(d)["rows"], [])

    def test_reference_pattern(self):
        self.assertEqual(board.REF_RE.findall("Replacement for #5378 damaged"), ["5378"])
        self.assertEqual(board.REF_RE.findall("replacement for order # RBP 7942"), ["7942"])
        self.assertEqual(board.REF_RE.findall("replacement, customer happy"), [])

    def _mcf(self, **kw):
        base = {"sfo_id": "SHOP-RBP1-1", "store": "RBP", "displayable_order_id": "RBP1", "order_status": "Complete",
                "received_at": ago(8), "order_status_at": ago(2), "amazon_shipment_id": "S1", "shipment_status": "SHIPPED",
                "shipped_at": ago(7), "package_number": "1", "tracking_number": "TBA111", "carrier_code": "AMZL",
                "estimated_arrival": ago(3), "tracking_status": "DELIVERED", "tracking_status_text": "Delivered",
                "delivered_at": ago(2), "last_event_at": ago(2), "last_event_text": "Delivered", "last_event_city": "Austin",
                "last_event_state": "TX", "events": [{"at": ago(2), "code": "EVENT_301", "text": "Delivered", "city": "Austin", "state": "TX"}],
                "fetched_at": ago(0.1)}
        base.update(kw)
        return base

    def mds(self, rows, mcf):
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW, mcf=mcf)
        return board.build("all", now=NOW, snap=sn)

    def test_amazon_delivery_marks_a_shopify_parcel_delivered(self):
        d = self.mds([row(row_id="a", order_name="# RBP1", carrier_name="Amazon Logistics US", tracking_number="TBA111",
                          status="pending", last_scan_at=None, kind="mcf", shipped_at=ago(7))], [self._mcf()])
        r = d.rows[0]
        self.assertEqual((r["cat"], r["source"], r["deliveredAt"].date()), ("delivered", "amazon", (NOW - board.timedelta(days=2)).date()))
        self.assertEqual(board.order_detail(d, "# RBP1")["packages"][0]["events"][0]["description"], "Amazon: Delivered")

    def test_unfulfilled_order_becomes_amazon_parcels(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(9), fulfillment_status="UNFULFILLED")
        d = self.mds([order], [self._mcf(tracking_status="IN_TRANSIT", delivered_at=None, last_event_text="Departed facility")])
        r = d.rows[0]
        self.assertEqual((r["row_kind"], r["stage"], r["normalized_tracking_status"]), ("amazon", "dispatched", "in_transit"))
        self.assertTrue(r["track_url"].startswith("https://track.amazon.com/"))
        # Amazon has it but has not shipped yet: the clock keeps running from the order date
        d = self.mds([order], [self._mcf(order_status="Received", shipment_status=None, shipped_at=None, package_number=None,
                                         tracking_number=None, tracking_status=None, delivered_at=None, last_event_at=None, events=[])])
        r = d.rows[0]
        self.assertEqual((r["row_kind"], r["stage"], r["cat"]), ("amazon", "pre_dispatch", "red"))
        self.assertIn("Received", r["last_scan_text"])

    def test_cancelled_amazon_order_leaves_the_order_not_dispatched(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(3))
        d = self.mds([order], [self._mcf(order_status="Cancelled")])
        self.assertEqual(d.rows[0]["row_kind"], "order")

    def test_second_amazon_order_is_a_reship(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(30))
        first = self._mcf(sfo_id="SHOP-RBP1-1", received_at=ago(29), shipped_at=ago(28), tracking_number="TBA1",
                          tracking_status="IN_TRANSIT", delivered_at=None, last_event_at=ago(20))
        second = self._mcf(sfo_id="SHOP-RBP1-2", received_at=ago(6), shipped_at=ago(5), tracking_number="TBA2")
        d = self.mds([order], [first, second])
        rr = board.reshipped_report(d)["rows"]
        self.assertEqual([(x["tracking"], x["how"]) for x in rr], [("TBA1", "second_amazon_order")])
        self.assertEqual([r["tracking_number"] for r in d.rows], ["TBA2"])

    def test_same_day_amazon_orders_are_a_split_not_a_reship(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(6))
        a = self._mcf(sfo_id="SHOP-RBP1-1", received_at=ago(5), tracking_number="TBA1", tracking_status="IN_TRANSIT", delivered_at=None)
        b = self._mcf(sfo_id="SHOP-RBP1-2", received_at=ago(4.9), tracking_number="TBA2", tracking_status="IN_TRANSIT", delivered_at=None)
        d = self.mds([order], [a, b])
        self.assertEqual(board.reshipped_report(d)["rows"], [])
        self.assertEqual(sorted(r["tracking_number"] for r in d.rows), ["TBA1", "TBA2"])

    def test_amazon_parcel_missing_from_a_fulfilled_shopify_order(self):
        shop = row(row_id="s", order_name="# RBP1", carrier_name="FedEx", tracking_number="FX1", status="in_transit",
                   shipped_at=ago(3), last_scan_at=ago(1), fulfillment_status="FULFILLED")
        d = self.mds([shop], [self._mcf(tracking_number="TBA9", tracking_status="IN_TRANSIT", delivered_at=None, last_event_at=ago(1))])
        extra = next(r for r in d.rows if r["tracking_number"] == "TBA9")
        self.assertEqual((extra["row_kind"], extra["amazon_extra"]), ("amazon", ["FedEx FX1"]))
        exc = [(e["type"], e["tracking"]) for e in board.exception_rows(d)]
        self.assertIn(("amazon_tracking_missing", "TBA9"), exc)
        self.assertNotIn("amazon_not_in_shopify", [t for t, _ in exc])
        # the same Amazon parcel already on the Shopify order is not an extra
        d = self.mds([shop], [self._mcf(tracking_number="FX1")])
        self.assertEqual(len(d.everything), 1)

    def test_unfulfillable_amazon_order_says_so(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(3))
        d = self.mds([order], [self._mcf(order_status="Unfulfillable", tracking_number=None)])
        self.assertIn("unfulfillable", d.rows[0]["amazon_status"])

    def test_out_for_delivery_from_amazon(self):
        d = self.mds([row(row_id="a", order_name="# RBP1", carrier_name="Amazon Logistics US", tracking_number="TBA111",
                          status="pending", last_scan_at=None, shipped_at=ago(2))],
                     [self._mcf(tracking_status="OUT_FOR_DELIVERY", delivered_at=None, last_event_at=ago(0.1))])
        self.assertEqual(d.rows[0]["normalized_tracking_status"], "out_for_delivery")

    def test_amazon_order_without_store_matches_only_a_unique_order_number(self):
        rows = [row(row_id="a", order_name="#7", store="CPC", tracking_number="X1", status="pending", last_scan_at=None),
                row(row_id="b", order_name="# RBP7", store="RBP", tracking_number="X2", status="pending", last_scan_at=None)]
        d = self.mds(rows, [self._mcf(store=None, sfo_id="MCF-7", displayable_order_id="7", tracking_number="ZZZ")])
        self.assertTrue(all(r["source"] != "amazon" for r in d.rows))      # ambiguous: left alone

    def test_freshness(self):
        self.assertEqual(board.freshness(snap([], [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.5), "last_status": "ok"}]), NOW)["state"], "stale")
        self.assertEqual(board.freshness(snap([], []), NOW)["state"], "unknown")
        f = board.freshness(snap([], [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.01), "last_status": "ok"},
                                      {"source": "shopify", "kind": "poll", "store": "CPC", "last_ok_at": ago(0.01), "last_status": "failed", "last_error": "boom"}]), NOW)
        self.assertEqual(f["state"], "failed")
        self.assertIn("CPC", f["message"])

    def test_csv_neutralises_formulas_and_has_brand(self):
        d = self.ds([row(row_id="a", tracking_number="=HYPERLINK(1)")])
        body = board.csv_shipments(board.select_rows(d))
        self.assertIn("\"'=HYPERLINK(1)\"", body)
        self.assertTrue(body.startswith('"brand"'))

    def test_public_row_has_no_note_text_or_address(self):
        d = self.ds([row(row_id="a", tracking_number="A", note_done=True)])
        pub = board.list_rows(d)["rows"][0]
        self.assertNotIn("note_done", pub)
        self.assertEqual((pub["city"], pub["state"]), ("Austin", "TX"))
        self.assertFalse({"ship_address1", "email", "phone", "note"} & set(pub))


if __name__ == "__main__":
    unittest.main()


class ShopifyOrderLinkTest(unittest.TestCase):
    """Each order links to its page in Shopify admin, built from the store's .myshopify.com address and the order id."""

    def test_link_uses_the_store_and_order_id(self):
        from flowmerce.modules.seo.config import config
        for store, brand in (("RBP", "ridhi"), ("CPC", "cpc")):
            shop = config.brands[brand].shop_domain
            if not shop.endswith(".myshopify.com"):
                continue
            url = board.shopify_url({"store": store, "order_id": 5551234567})
            self.assertEqual(url, f"https://admin.shopify.com/store/{shop[:-len('.myshopify.com')]}/orders/5551234567")

    def test_no_link_without_a_known_store_or_order_id(self):
        self.assertEqual(board.shopify_url({"store": "RBP", "order_id": None}), "")
        self.assertEqual(board.shopify_url({"store": "RBP", "order_id": 0}), "")
        self.assertEqual(board.shopify_url({"store": "XYZ", "order_id": 123}), "")
        self.assertEqual(board.shopify_url({"store": "CPC", "order_id": "not-a-number"}), "")
