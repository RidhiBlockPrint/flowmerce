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

    def test_clock_runs_from_the_last_carrier_scan(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", order_name="#1", shipped_at=ago(10), last_scan_at=ago(1)),   # scanned yesterday
            row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(12), last_scan_at=ago(5)),   # yellow
            row(row_id="c", tracking_number="C", order_name="#3", shipped_at=ago(20), last_scan_at=ago(7)),   # orange
            row(row_id="e", tracking_number="E", order_name="#6", shipped_at=ago(15), last_scan_at=ago(10)),  # critical
            row(row_id="f", tracking_number="F", order_name="#7", shipped_at=ago(2), last_scan_at=None),      # no scan: from dispatch
            row(row_id="o", row_kind="order", order_name="#4", placed_at=ago(3), tracking_number=None,        # not sent: not tracked
                carrier_name=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="d", tracking_number="D", order_name="#5", status="delivered", delivered_at=ago(2)),
        ])
        cats = {r["order_number"]: r["cat"] for r in d.rows}
        self.assertEqual(cats, {"#1": "on_track", "#2": "yellow", "#3": "orange", "#6": "red", "#7": "on_track", "#5": "delivered"})
        self.assertNotIn("#4", {r["order_number"] for r in d.everything})
        s = board.summary(d)
        self.assertEqual(s["activeTotal"], 5)
        self.assertEqual((s["stage"]["dispatched"], s["delivered"]), (5, 1))
        self.assertIn("1 shipment(s) have had no carrier update for 9+ days", s["banner"])

    def test_journey_splits_active_parcels_by_tracking_status(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", order_name="#1", status="pending", last_scan_at=None, shipped_at=ago(1)),
            row(row_id="b", tracking_number="B", order_name="#2", status="in_transit", shipped_at=ago(2)),
            row(row_id="c", tracking_number="C", order_name="#3", status="in_transit", shipped_at=ago(12), last_scan_at=ago(10)),
            row(row_id="e", tracking_number="E", order_name="#4", status="out_for_delivery", shipped_at=ago(3)),
            row(row_id="o", row_kind="order", order_name="#5", placed_at=ago(11), tracking_number=None,
                carrier_name=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="d", tracking_number="D", order_name="#6", status="delivered", delivered_at=ago(2)),
        ])
        s = board.summary(d)
        j = {x["key"]: x for x in s["journey"]}
        self.assertEqual([x["key"] for x in s["journey"]], ["dispatched", "in_transit", "out_for_delivery", "delivered"])
        self.assertEqual({k: v["value"] for k, v in j.items()},
                         {"dispatched": 1, "in_transit": 2, "out_for_delivery": 1, "delivered": 1})
        # the three parcel stages add up to the active total
        self.assertEqual(j["dispatched"]["value"] + j["in_transit"]["value"] + j["out_for_delivery"]["value"], s["activeTotal"])
        self.assertEqual(j["in_transit"]["flags"], [{"label": "critical", "value": 1, "tone": "crit", "cat": "red"}])
        self.assertEqual(s["delivery30"]["delivered"], 1)

    def test_home_figures_match_the_board(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", order_name="#1", status="exception", raw_status="FAILURE",
                shipped_at=ago(20), last_scan_at=ago(12), last_scan_text="Delivery attempted"),
            row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(2)),
            row(row_id="c", tracking_number="C", order_name="#3", store="CPC", shipped_at=ago(1)),
            row(row_id="d", tracking_number="D", order_name="#4", status="delivered", delivered_at=ago(2)),
            row(row_id="u", tracking_number="U", order_name="#5", carrier_name="Amazon Logistics US", status="pending",
                last_scan_at=None, shipped_at=ago(20)),
        ])
        brand_of = {r["order_number"]: r["brand"] for r in d.rows}
        ridhi, cpc = brand_of["#1"], brand_of["#3"]
        h = board.home_figures(d, [ridhi, cpc])
        s = board.summary(d)
        self.assertEqual(h["all"]["active"], s["activeTotal"])           # Home and Shipping agree
        self.assertEqual((h["all"]["problems"], h["all"]["critical"], h["all"]["handChecks"], h["all"]["delivered30d"]),
                         (2, 1, 1, 1))
        self.assertEqual((h["byBrand"][ridhi]["active"], h["byBrand"][cpc]["active"]), (3, 1))
        self.assertEqual([(t["order"], t["label"]) for t in h["all"]["top"]], [("#5", "Invalid tracking"), ("#1", "Critical 9+ days")])
        only_cpc = board.home_figures(d, [cpc])
        self.assertEqual((only_cpc["all"]["active"], only_cpc["all"]["top"], list(only_cpc["byBrand"])), (1, [], [cpc]))

    def test_a_number_no_carrier_ever_reported_on_is_invalid_tracking(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", order_name="#1", carrier_name="Amazon Logistics US", status="pending",
                last_scan_at=None, shipped_at=ago(20)),
            # Amazon WITH carrier updates follows the clock (from its last scan)
            row(row_id="b", tracking_number="B", order_name="#2", carrier_name="Amazon Logistics US", status="in_transit",
                shipped_at=ago(20), last_scan_at=ago(1)),
            # a named carrier that never reported anything (e.g. # RBP7437): also invalid
            row(row_id="u", tracking_number="U26", order_name="#3", carrier_name="USPS", status="pending", last_scan_at=None,
                shipped_at=ago(26)),
            # shipped yesterday: no first scan yet is normal, the clock runs from dispatch
            row(row_id="v", tracking_number="U1", order_name="#4", carrier_name="USPS", status="pending", last_scan_at=None,
                shipped_at=ago(1)),
            # the carrier knows the label (a status, no scan yet): a real number, on the clock from dispatch
            row(row_id="i", tracking_number="I", order_name="#5", status="info_received", last_scan_at=None, shipped_at=ago(10)),
        ])
        by = {r["tracking_number"]: r for r in d.rows}
        self.assertEqual({t: by[t]["cat"] for t in by}, {"A": "invalid", "B": "on_track", "U26": "invalid", "U1": "on_track",
                                                         "I": "red"})
        self.assertEqual(board.checks(d)["counts"]["invalid"], 2)
        self.assertEqual({(e["order"], e["type"]) for e in board.exception_rows(d)}, {("#1", "invalid_tracking"), ("#3", "invalid_tracking")})
        self.assertEqual(board.list_rows(d, cat="invalid")["total"], 2)

    def test_a_carrier_exception_is_on_the_clock_like_any_parcel(self):
        d = self.ds([
            # a failure WITH carrier events: Critical when the last scan is 9+ days old; the status word is kept for display
            row(row_id="b", tracking_number="E", order_name="#2", status="exception", raw_status="FAILURE",
                shipped_at=ago(20), last_scan_at=ago(10), last_scan_text="Delivery attempted"),
            # the hub's one status word is still a word from the carrier: on the clock, not invalid
            row(row_id="a", tracking_number="H", status="exception", raw_status="failure", shipped_at=ago(41),
                last_scan_at=ago(23), last_scan_text="Shopify shipment status: failure"),
            # the team checked DHL and marked the parcel delivered
            row(row_id="c", tracking_number="M", order_name="#3", status="exception", raw_status="failure", shipped_at=ago(41),
                last_scan_at=ago(23), last_scan_text="Shopify shipment status: failure", team_mark="delivered"),
        ])
        by = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual((by["E"]["cat"], by["E"]["exc"]), ("red", "failure"))
        self.assertEqual(by["H"]["cat"], "red")
        self.assertEqual(by["M"]["cat"], "delivered")
        self.assertEqual(board.exception_rows(d), [])                 # no "carrier exception" list any more
        self.assertEqual(board.summary(d)["critical"], 2)

    def test_team_marks_apply_to_any_parcel(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", carrier_name="Unknown carrier", status="pending", last_scan_at=None, team_mark="lost"),
            row(row_id="b", tracking_number="B", order_name="#2", team_mark="lost"),
            row(row_id="c", tracking_number="C", order_name="#3", team_mark="failed"),
            row(row_id="e", tracking_number="E", order_name="#4", team_mark="delivered"),
            row(row_id="f", tracking_number="F", order_name="#5", team_mark="in_transit", last_scan_at=ago(10)),
        ])
        by = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual({t: by[t]["resolved"]["outcome"] for t in ("A", "B", "C")}, {"A": "lost", "B": "lost", "C": "failed"})
        self.assertEqual(by["C"]["resolved"]["label"], "Couldn't deliver")
        self.assertEqual(by["E"]["cat"], "delivered")
        self.assertEqual(by["F"]["cat"], "red")                         # "still in transit" changes nothing
        self.assertEqual({r["tracking_number"] for r in d.active}, {"F"})
        self.assertEqual(board.list_rows(d, cat="resolved")["total"], 3)

    def test_cancelled_and_refunded_are_left_out(self):
        d = self.ds([row(row_id="a", tracking_number="A", cancelled_at=ago(1)),
                     row(row_id="b", tracking_number="B", order_name="#2", financial_status="REFUNDED"),
                     row(row_id="c", tracking_number="C", order_name="#3")])
        self.assertEqual([r["order_number"] for r in d.rows], ["#3"])
        self.assertEqual(board.order_detail(d, "#R1")["excluded"], "cancelled")

    def test_each_order_is_in_one_section_only(self):
        d = self.ds([
            row(row_id="a", tracking_number="A", last_scan_at=ago(10), last_scan_text="Arrived at hub"),          # critical
            row(row_id="s", row_kind="shipment", tracking_number=None, order_name="#3", status="pending", last_scan_at=None),
            row(row_id="c", tracking_number="DUP", order_name="#4"), row(row_id="e", tracking_number="DUP", order_name="#5"),
            # past its promised date but scanned yesterday: on track, no "overdue" check any more
            row(row_id="f", tracking_number="F", order_name="#6", shipped_at=ago(3), eta=(NOW - timedelta(days=2)).date().isoformat()),
            # one order, two parcels: a critical one and one without tracking -> the whole order is under Tracking missing
            row(row_id="g", tracking_number="G", order_id=7, order_name="#7", last_scan_at=ago(12)),
            row(row_id="h", row_kind="shipment", tracking_number=None, order_id=7, order_name="#7", status="pending", last_scan_at=None),
        ])
        types = {(x["order"], x["type"]) for x in board.exception_rows(d)}
        self.assertEqual(types, {("#3", "missing_tracking"), ("#4", "duplicate_tracking"), ("#5", "duplicate_tracking"),
                                 ("#7", "missing_tracking")})
        k = {x["key"]: x["value"] for x in board.kpis(d)}
        self.assertEqual((k[""], k["red"], k["tracking_missing"], k["checks"], k["on_track"]), (7, 1, 3, 2, 1))
        self.assertEqual([r["order"] for r in board.list_rows(d, cat="red")["rows"]], ["#R1"])    # #7 is not also in Critical
        g = next(r for r in d.rows if r["tracking_number"] == "G")
        self.assertEqual((g["cat"], g["ownCat"]), ("tracking_missing", "red"))
        self.assertIn("this parcel: Critical", board.public_row(d, g, {})["label"])
        # each order once in the hand checks, with every issue as a tag
        self.assertEqual(sorted(r["order"] for r in board.checks(d)["exceptions"]["rows"]), ["#3", "#4", "#5", "#7"])

    def test_open_parcels_older_than_120_days_are_not_tracked(self):
        d = self.ds([
            row(row_id="a", tracking_number="OLD", order_name="#1", shipped_at=ago(130), last_scan_at=ago(125)),
            row(row_id="b", tracking_number="EDGE", order_name="#2", shipped_at=ago(119), last_scan_at=ago(100)),
            row(row_id="c", tracking_number="DONE", order_name="#3", shipped_at=ago(130), status="delivered", delivered_at=ago(90)),
        ])
        self.assertEqual({r["tracking_number"]: r["cat"] for r in d.everything}, {"EDGE": "red", "DONE": "delivered"})

    def test_orders_not_sent_yet_are_not_tracked(self):
        d = self.ds([
            row(row_id="o1", row_kind="order", order_name="#9", placed_at=ago(11), note_done=True, fulfillment_status="UNFULFILLED",
                tracking_number=None, status=None, shipped_at=None, last_scan_at=None),
            row(row_id="o2", row_kind="amazon", order_name="#10", kind="mcf", carrier_name="Amazon Logistics US", tracking_number=None,
                status="pending", shipped_at=None, last_scan_at=None, placed_at=ago(12), amazon_status="Amazon accepted"),
            row(row_id="a", tracking_number="A", note_done=True),
        ])
        self.assertEqual([r["order_number"] for r in d.everything], ["#R1"])
        self.assertEqual(board.list_rows(d)["total"], 1)
        self.assertIsNone(board.order_detail(d, "#9"))

    def test_amazon_word_on_the_order_delivers_it(self):
        d = self.ds([
            # Amazon's own word on the order is delivered, Shopify never updated
            row(row_id="b", tracking_number="B", order_id=4640, order_name="#4640", placed_at=ago(70),
                fulfillment_status="PARTIALLY_FULFILLED", amazon_status="Package delivered near the front door or porch."),
            # out for delivery is not delivered: still listed
            row(row_id="c", tracking_number="C", order_id=8447, order_name="#8447", placed_at=ago(12),
                fulfillment_status="PARTIALLY_FULFILLED", amazon_status="Package is out for delivery."),
        ])
        self.assertEqual([r["order_number"] for r in d.active], ["#8447"])
        b = next(r for r in d.everything if r["order_number"] == "#4640")
        self.assertEqual(b["cat"], "delivered")
        self.assertIn("Amazon says", b["deliveredBy"]["detail"])
        self.assertEqual(board.delivered_orders(d), {("RBP", "4640")})

    def test_amazon_word_shows_only_on_the_amazon_parcel(self):
        common = dict(order_id=8183, order_name="#R8183", amazon_status="Shipped by Amazon",
                      amazon_tracking="9361289715870156749864")
        d = self.ds([row(row_id="u", carrier_name="USPS", tracking_number="9361289715870156749864", **common),
                     row(row_id="f", carrier_name="FedEx", tracking_number="385114394936", **common)])
        by = {r["row_id"]: board.public_row(d, r, {}) for r in d.everything}
        self.assertEqual(by["u"]["amazonStatus"], "Shipped by Amazon")
        self.assertIsNone(by["f"]["amazonStatus"])

    def test_team_in_transit_mark_does_not_count_once_the_order_is_delivered(self):
        d = self.ds([
            # # RBP7010: the team marked the Amazon parcel "still in transit"; another parcel of the order was delivered later
            row(row_id="a", tracking_number="A", order_id=7010, order_name="#R7010", carrier_name="Unknown carrier",
                status="pending", last_scan_at=None, team_mark="in_transit", team_mark_at=ago(0.3)),
            row(row_id="b", tracking_number="B", order_id=7010, order_name="#R7010", status="delivered", delivered_at=ago(0.1)),
        ])
        self.assertEqual(d.active, [])
        self.assertEqual({r["cat"] for r in d.everything}, {"delivered"})

    def test_value_at_risk_counts_each_order_once(self):
        d = self.ds([row(row_id="a", tracking_number="A", total=40.0, last_scan_at=ago(10)),
                     row(row_id="b", tracking_number="B", total=40.0, last_scan_at=ago(10)),
                     row(row_id="c", tracking_number="C", order_name="#2", total=10.0, last_scan_at=ago(10))])
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
        d = self.ds([row(row_id="a", tracking_number="A", shipped_at=ago(12), last_scan_at=ago(10)),
                     row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(1), status="exception", raw_status="DELAYED"),
                     row(row_id="c", tracking_number="C", order_name="#3", shipped_at=ago(8), last_scan_at=ago(5))])
        out = board.list_rows(d, cat="")
        self.assertEqual([r["order"] for r in out["rows"]], ["#R1", "#3", "#2"])     # critical, yellow, on track
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        self.assertEqual(board.list_rows(d, cat="nomove")["total"], 0)              # an old filter lists nothing
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
        parcel = row(row_id="a", tracking_number="A", order_id=5151, order_name="#U1", last_scan_at=ago(10))
        d = self.ds([parcel])
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        r = board.annotate(d, "#U1", "outcome", "Refunded", "Ops")
        self.assertEqual((r["annotation"]["outcome"], r["annotation"]["outcomeBy"]), ("refunded", "Ops"))
        self.assertIn("Resolved as refunded", r["packages"][0]["action"])
        self.assertEqual(board.list_rows(d, cat="red")["total"], 0)               # gone from Critical
        self.assertEqual(next(k for k in board.kpis(d) if k["key"] == "")["value"], 0)   # and from the active total
        res = board.list_rows(d, cat="resolved")
        self.assertEqual((res["total"], res["rows"][0]["cat"], res["rows"][0]["resolved"]["label"]), (1, "resolved", "Refunded"))
        d2 = self.ds([parcel])                                                     # a fresh read keeps it resolved
        self.assertEqual(board.list_rows(d2, cat="red")["total"], 0)
        board.annotate(d, "#U1", "clear_outcome", "", "Ops")                        # undo: back in Critical
        self.assertEqual(board.list_rows(d, cat="red")["total"], 1)
        board.annotate(d, "#U1", "outcome", "Delivered", "Ops")                     # delivered: in no list at all
        self.assertEqual((board.list_rows(d, cat="red")["total"], board.list_rows(d, cat="resolved")["total"]), (0, 0))
        with self.assertRaises(Exception):
            board.annotate(d, "#U1", "outcome", "sold", "Ops")
        with self.assertRaises(Exception):
            board.annotate(d, "#U1", "outcome", "failed", "Ops")                  # a parcel mark, not an order outcome
        board.annotate(d, "#U1", "clear_outcome", "", "Ops")

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
        self.assertEqual([(r["tracking_number"], r["cat"]) for r in d.rows], [("DLY", "red")])
        self.assertEqual(board.exception_rows(d), [])

    def test_import_preview_writes_nothing_and_checks_rows(self):
        d = self.ds([row(row_id="s", row_kind="shipment", tracking_number=None, order_name="#S1", status="pending", last_scan_at=None),
                     row(row_id="a", tracking_number="A", order_name="#S2")])
        res = board.preview_import(d, "order_number,tracking_number,carrier\n#S1,ABC123456,DHL Express\n#S2,ABC999999,DHL Express\n#S3,ABC123457,DHL Express\n#S1,12,DHL Express")
        self.assertEqual([r["outcome"] for r in res["rows"]], ["will_update", "skip_has_tracking", "error", "error"])
        self.assertTrue(res["previewOnly"])

    def test_amazon_rows(self):
        d = self.ds([
            # Amazon shipped it, Shopify shows the order unfulfilled, and no carrier word yet: Invalid tracking, both issues
            row(row_id="9:1", row_kind="amazon", order_name="#A1", kind="mcf", carrier_name="USPS", tracking_number="9361289715570003153164",
                status="pending", source="amazon", shipped_at=ago(4), last_scan_at=None, last_scan_text="Amazon: Shipped by Amazon",
                fulfillment_status="UNFULFILLED", note_done=True, placed_at=ago(6), amazon_status="Shipped by Amazon"),
            # with Amazon, not shipped yet: not tracked
            row(row_id="9:2", row_kind="amazon", order_name="#A2", order_id=2, kind="mcf", carrier_name="Amazon Logistics US",
                tracking_number=None, status="pending", source="amazon", shipped_at=None, last_scan_at=None, placed_at=ago(11),
                fulfillment_status="UNFULFILLED", amazon_status="Amazon accepted"),
            # moving with the carrier but Shopify does not know: Fix in Shopify
            row(row_id="9:5", row_kind="amazon", order_name="#A5", order_id=5, kind="mcf", carrier_name="USPS", tracking_number="9400111",
                status="in_transit", source="amazon", shipped_at=ago(4), last_scan_at=ago(1), fulfillment_status="UNFULFILLED"),
            row(row_id="t", tracking_number="DHLX", order_name="#A4", order_id=4, kind="mcf", carrier_name="DHL Express",
                status="pending", last_scan_at=None, shipped_at=ago(12)),
        ])
        by = {r["order_number"]: r for r in d.rows}
        self.assertEqual(set(by), {"#A1", "#A4", "#A5"})
        self.assertEqual({o: by[o]["cat"] for o in by}, {"#A1": "invalid", "#A4": "invalid", "#A5": "checks"})
        exc = {(x["order"], x["type"]) for x in board.exception_rows(d)}
        self.assertIn(("#A1", "amazon_not_in_shopify"), exc)
        self.assertIn(("#A5", "amazon_not_in_shopify"), exc)
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

    def test_parcel_delivered_by_another_carrier_leaves_the_delay_figures(self):
        rows = [
            # #5680: a USPS label that never moved (critical) while UPS delivered the same order
            row(row_id="a", tracking_number="USPS1", order_id=5680, order_name="#5680", shipment_id="s1", carrier_name="USPS",
                status="in_transit", last_scan_at=ago(58), last_scan_text="USPS Awaiting Item", shipped_at=ago(58), placed_at=ago(60)),
            row(row_id="b", tracking_number="UPS1", order_id=5680, order_name="#5680", shipment_id="s2", carrier_name="UPS",
                status="delivered", delivered_at=ago(54), shipped_at=ago(59), placed_at=ago(60)),
            # same carrier, one delivered and one open: may be a split shipment, stays on the board
            row(row_id="c", tracking_number="SPL1", order_id=700, order_name="#700", shipment_id="s3", carrier_name="USPS",
                status="in_transit", last_scan_at=ago(15), shipped_at=ago(20), placed_at=ago(21)),
            row(row_id="d", tracking_number="SPL2", order_id=700, order_name="#700", shipment_id="s4", carrier_name="USPS",
                status="delivered", delivered_at=ago(16), shipped_at=ago(20), placed_at=ago(21)),
            # sent AFTER the other carrier delivered (an exchange / more items): stays on the board
            row(row_id="e", tracking_number="LATER1", order_id=800, order_name="#800", shipment_id="s5", carrier_name="FedEx",
                status="pending", last_scan_at=None, shipped_at=ago(12), placed_at=ago(40)),
            row(row_id="f", tracking_number="DONE1", order_id=800, order_name="#800", shipment_id="s6", carrier_name="UPS",
                status="delivered", delivered_at=ago(30), shipped_at=ago(35), placed_at=ago(40)),
            # still scanning after the other carrier delivered (a split still moving): stays on the board
            row(row_id="g", tracking_number="MOVING1", order_id=900, order_name="#900", shipment_id="s7", carrier_name="DHL Express",
                status="in_transit", last_scan_at=ago(2), shipped_at=ago(15), placed_at=ago(16)),
            row(row_id="h", tracking_number="DONE2", order_id=900, order_name="#900", shipment_id="s8", carrier_name="UPS",
                status="delivered", delivered_at=ago(10), shipped_at=ago(14), placed_at=ago(16)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        old = {r["tracking_number"]: r for r in d.everything}
        self.assertEqual((old["USPS1"]["reshipped"]["how"], old["USPS1"]["reshipped"]["newCarrier"],
                          old["USPS1"]["reshipped"]["newTracking"]), ("delivered_by_other_carrier", "UPS", "UPS1"))
        self.assertEqual((old["USPS1"]["cat"], old["USPS1"]["deliveredBy"]["by"]), ("delivered", "order"))   # UPS delivered it
        # an order that was delivered is no problem: every other open parcel of it counts as delivered too
        # (a same-carrier parcel, one sent after the delivery, one still scanning)
        for t in ("SPL1", "LATER1", "MOVING1"):
            self.assertEqual((old[t]["cat"], old[t]["deliveredBy"]["by"]), ("delivered", "order"), t)
        self.assertEqual({r["tracking_number"] for r in d.active}, set())
        self.assertFalse(board.exception_rows(d))
        self.assertEqual(board.list_rows(d, cat="reshipped")["total"], 0)
        self.assertEqual(board.list_rows(d, cat="resolved")["total"], 0)          # delivered is never "resolved"

    def test_delivered_order_hides_its_no_tracking_fulfilment_and_scan_says_delivered(self):
        rows = [
            # # RBP6462: DHL parcel delivered; a later Shopify fulfilment with no tracking number
            row(row_id="a", tracking_number="2375772626", order_id=6462, order_name="#R6462", shipment_id="s1",
                status="delivered", delivered_at=ago(30), shipped_at=ago(33), placed_at=ago(47)),
            row(row_id="b", row_kind="shipment", tracking_number=None, order_id=6462, order_name="#R6462",
                shipment_id="s2", status="pending", last_scan_at=None, shipped_at=ago(2), placed_at=ago(47)),
            # the carrier's last scan says delivered, the status never caught up
            row(row_id="c", tracking_number="DLV1", order_id=6500, order_name="#R6500", status="in_transit",
                last_scan_at=ago(3), last_scan_text="Delivered, Front Door/Porch", shipped_at=ago(12), placed_at=ago(13)),
            # dispatched without tracking and nothing delivered: still a problem
            row(row_id="d", row_kind="shipment", tracking_number=None, order_id=6600, order_name="#R6600",
                shipment_id="s3", status="pending", last_scan_at=None, shipped_at=ago(4), placed_at=ago(6)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        orders = {e["order"] for e in board.exception_rows(d)}
        self.assertEqual(orders, {"#R6600"})
        self.assertEqual({r["order_number"] for r in d.active}, {"#R6600"})
        nt = next(r for r in d.everything if r["row_id"] == "b")
        self.assertIn("no tracking number", nt["deliveredBy"]["detail"])
        self.assertEqual(next(r for r in d.everything if r["row_id"] == "c")["cat"], "delivered")   # scan says delivered
        self.assertEqual(board.public_row(d, nt, {})["cat"], "delivered")

    def test_two_orders_in_one_parcel_are_both_delivered(self):
        rows = [
            # CPC #6949 owns the tracking row of DHL 4503128464 and it is delivered
            row(row_id="a", store="CPC", tracking_number="4503128464", order_id=6949, order_name="#6949",
                shipment_id="s1", status="delivered", delivered_at=ago(1), shipped_at=ago(6), placed_at=ago(60)),
            # #6948 went in the same box: a fulfilment row that only reads the shared number (still "in transit")
            row(row_id="b", row_kind="shipment", store="CPC", tracking_number="4503128464", order_id=6948,
                order_name="#6948", shipment_id="s2", status="in_transit", shipped_at=ago(6), placed_at=ago(60)),
            # same number in the other store is a different parcel
            row(row_id="c", row_kind="shipment", store="RBP", tracking_number="4503128464", order_id=7000,
                order_name="#R7000", shipment_id="s3", status="in_transit", shipped_at=ago(6), placed_at=ago(8)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        b = next(r for r in d.everything if r["row_id"] == "b")
        self.assertFalse(b["missingTracking"])                     # the shared number counts as its tracking
        self.assertEqual((b["cat"], b["deliveredBy"]["outcome"]), ("delivered", "delivered"))
        self.assertIn("#6949", b["deliveredBy"]["detail"])
        self.assertEqual({r["order_number"] for r in d.active}, {"#R7000"})
        self.assertNotIn("#6948", {e["order"] for e in board.exception_rows(d)})
        self.assertEqual(board.public_row(d, b, {})["cat"], "delivered")

    def test_any_number_on_the_fulfilment_counts_when_another_order_owns_its_row(self):
        rows = [
            # CPC #8426 owns the tracking row of TBA336415473219, delivered by Amazon
            row(row_id="a", store="CPC", carrier_name="Amazon Logistics US", tracking_number="TBA336415473219",
                order_id=8426, order_name="#8426", shipment_id="s1", status="delivered", delivered_at=ago(1),
                shipped_at=ago(5), placed_at=ago(10)),
            # #8446's fulfilment lists TBA336415473219 AND a USPS number; its row shows only the USPS one
            row(row_id="b", store="CPC", carrier_name="USPS", tracking_number="9361289704070543546395", order_id=8446,
                order_name="#8446", shipment_id="s2", status="pending", last_scan_at=None, shipped_at=ago(5),
                placed_at=ago(10)),
            # a parcel whose fulfilment lists only its own number stays open
            row(row_id="c", store="CPC", tracking_number="OPEN1", order_id=8500, order_name="#8500", shipment_id="s3",
                shipped_at=ago(3), placed_at=ago(4)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set(),
                            numbers={"s1": {"TBA336415473219"}, "s2": {"TBA336415473219", "9361289704070543546395"},
                                     "s3": {"OPEN1"}})
        d = board.build("all", now=NOW, snap=sn)
        b = next(r for r in d.everything if r["row_id"] == "b")
        self.assertEqual(b["cat"], "delivered")
        self.assertIn("#8426", b["deliveredBy"]["detail"])
        self.assertEqual({r["order_number"] for r in d.active}, {"#8500"})

    def test_fulfilment_without_any_number_is_still_missing_tracking(self):
        d = self.ds([row(row_id="d", row_kind="shipment", tracking_number=None, order_name="#R1", status="pending",
                         last_scan_at=None, shipped_at=ago(4), placed_at=ago(6))])
        self.assertTrue(d.everything[0]["missingTracking"])
        self.assertIn("missing_tracking", {e["type"] for e in board.exception_rows(d)})

    def test_amazon_extra_parcel_is_delivered_when_the_shopify_order_arrived(self):
        # #7254: Shopify lists two Amazon parcels, both delivered; Amazon's extra parcel said "delivery date unavailable"
        rows = [
            row(row_id="a", tracking_number="TBA1", order_id=7254, order_name="#7254", shipment_id="s1",
                carrier_name="Amazon Logistics US", status="delivered", delivered_at=ago(47), shipped_at=ago(50), placed_at=ago(52)),
            row(row_id="b", tracking_number="TBA2", order_id=7254, order_name="#7254", shipment_id="s1",
                carrier_name="Amazon Logistics US", status="delivered", delivered_at=ago(32), shipped_at=ago(50), placed_at=ago(52)),
            row(row_id="c", row_kind="amazon", tracking_number="TBA3", order_id=7254, order_name="#7254",
                carrier_name="Amazon Logistics US", status="exception", raw_status="DELAYED", last_scan_at=ago(42),
                last_scan_text="Delivery date is currently unavailable", shipped_at=ago(50), placed_at=ago(52),
                amazon_extra=["Amazon Logistics US TBA1", "Amazon Logistics US TBA2"]),
            # an extra Amazon parcel while a Shopify parcel is still on its way: stays open
            row(row_id="d", tracking_number="TBA4", order_id=7300, order_name="#7300", shipment_id="s2",
                carrier_name="Amazon Logistics US", status="in_transit", last_scan_at=ago(1), shipped_at=ago(3), placed_at=ago(4)),
            row(row_id="e", row_kind="amazon", tracking_number="TBA5", order_id=7300, order_name="#7300",
                carrier_name="Amazon Logistics US", status="exception", raw_status="DELAYED", last_scan_at=ago(1),
                shipped_at=ago(3), placed_at=ago(4), amazon_extra=["Amazon Logistics US TBA4"]),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        active = {r["tracking_number"] for r in d.active}
        self.assertNotIn("TBA3", active)
        self.assertIn("TBA5", active)
        self.assertFalse([e for e in board.exception_rows(d) if e["order"] == "#7254"])
        p = {x["tracking"]: x for x in board.order_detail(d, "#7254")["packages"]}
        self.assertEqual((p["TBA3"]["cat"], p["TBA3"]["label"]), ("delivered", "Delivered"))
        self.assertIn("TBA1", p["TBA3"]["deliveredBy"]["detail"])

    def test_reshipped_parcel_is_delivered_when_its_replacement_arrived(self):
        rows = [
            row(row_id="a", tracking_number="OLDU", order_id=6127, order_name="#R6127", shipment_id="s1", carrier_name="USPS",
                status="in_transit", last_scan_at=ago(51), shipped_at=ago(50), placed_at=ago(52)),
            row(row_id="b", tracking_number="NEWU", order_id=6127, order_name="#R6127", shipment_id="s2", carrier_name="USPS",
                status="delivered", delivered_at=ago(43), shipped_at=ago(45), placed_at=ago(52)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        old = next(r for r in d.everything if r["tracking_number"] == "OLDU")
        self.assertEqual((old["cat"], old["deliveredBy"]["by"]), ("delivered", "order"))
        self.assertEqual(board.reshipped_report(d)["rows"], [])      # delivered, not waiting in Reshipped

    def test_same_carrier_parcel_sent_again_later_and_delivered(self):
        rows = [
            # # RBP6127: USPS label never moved; a second USPS parcel sent 5 days later was delivered
            row(row_id="a", tracking_number="OLDU", order_id=6127, order_name="#R6127", shipment_id="s1", carrier_name="USPS",
                status="in_transit", last_scan_at=ago(51), shipped_at=ago(50), placed_at=ago(52)),
            row(row_id="b", tracking_number="NEWU", order_id=6127, order_name="#R6127", shipment_id="s2", carrier_name="USPS",
                status="delivered", delivered_at=ago(43), shipped_at=ago(45), placed_at=ago(52)),
        ]
        sn = board.Snapshot(rows, [{"source": "shopify", "kind": "import", "last_ok_at": ago(0.05), "last_status": "ok"}], NOW,
                            items={}, replacements=[], reship_notes=set())
        d = board.build("all", now=NOW, snap=sn)
        old = next(r for r in d.everything if r["tracking_number"] == "OLDU")
        self.assertEqual(old["reshipped"]["how"], "delivered_by_later_parcel")
        self.assertFalse(board.exception_rows(d))

    def test_one_checks_row_per_order_with_every_issue_as_a_tag(self):
        d = self.ds([
            row(row_id="a", row_kind="shipment", tracking_number=None, order_id=6927, order_name="#6927", status="pending",
                last_scan_at=None),
            row(row_id="b", row_kind="amazon", tracking_number="TBA7", order_id=6927, order_name="#6927", kind="mcf",
                carrier_name="Amazon Logistics US", status="in_transit", last_scan_at=ago(1), fulfillment_status="UNFULFILLED"),
        ])
        ex = board.checks(d)["exceptions"]
        self.assertEqual([r["order"] for r in ex["rows"]], ["#6927"])
        self.assertEqual(ex["rows"][0]["types"], ["missing_tracking", "amazon_not_in_shopify"])
        self.assertEqual((ex["total"], ex["counts"]["missing_tracking"], ex["counts"]["amazon_not_in_shopify"]), (1, 1, 1))
        self.assertEqual(board.checks(d)["counts"], {"tracking_missing": 1, "invalid": 0, "checks": 0})

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
        if kw.get("tracking_status", "DELIVERED") != "DELIVERED":   # Amazon's text follows its status, as in real data
            text = str(kw["tracking_status"] or "Shipped").replace("_", " ").capitalize()
            base.update(tracking_status_text=text, last_event_text=text,
                        events=[{"at": ago(1), "code": "EVENT_101", "text": text, "city": "Austin", "state": "TX"}])
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
        # Amazon has it but has not shipped yet: not dispatched, so not tracked
        d = self.mds([order], [self._mcf(order_status="Received", shipment_status=None, shipped_at=None, package_number=None,
                                         tracking_number=None, tracking_status=None, delivered_at=None, last_event_at=None, events=[])])
        self.assertEqual((d.rows, d.everything), ([], []))

    def test_cancelled_amazon_order_is_shown_nowhere(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(3))
        self.assertEqual(self.mds([order], [self._mcf(order_status="Cancelled")]).everything, [])

    def test_second_amazon_order_is_a_reship(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(30))
        first = self._mcf(sfo_id="SHOP-RBP1-1", received_at=ago(29), shipped_at=ago(28), tracking_number="TBA1",
                          tracking_status="IN_TRANSIT", delivered_at=None, last_event_at=ago(20))
        second = self._mcf(sfo_id="SHOP-RBP1-2", received_at=ago(6), shipped_at=ago(5), tracking_number="TBA2")
        d = self.mds([order], [first, second])
        old = next(r for r in d.everything if r["tracking_number"] == "TBA1")
        self.assertEqual(old["reshipped"]["how"], "second_amazon_order")
        self.assertEqual(old["cat"], "delivered")                    # the second order was delivered: order delivered
        self.assertEqual([r["tracking_number"] for r in d.rows], ["TBA2"])
        # while the second Amazon order is still on its way, the first waits in Reshipped
        second_moving = self._mcf(sfo_id="SHOP-RBP1-2", received_at=ago(6), shipped_at=ago(5), tracking_number="TBA2",
                                  tracking_status="IN_TRANSIT", delivered_at=None, last_event_at=ago(1))
        d = self.mds([order], [first, second_moving])
        rr = board.reshipped_report(d)["rows"]
        self.assertEqual([(x["tracking"], x["how"]) for x in rr], [("TBA1", "second_amazon_order")])

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

    def test_unfulfillable_amazon_order_is_not_tracked(self):
        order = row(row_id="o", row_kind="order", order_name="# RBP1", tracking_number=None, carrier_name=None, status=None,
                    shipped_at=None, last_scan_at=None, placed_at=ago(3))
        self.assertEqual(self.mds([order], [self._mcf(order_status="Unfulfillable", tracking_number=None)]).everything, [])

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


class BuiltBoardCacheTest(unittest.TestCase):
    """The built board is reused per brand until the data or a team mark changes (pages were ~2 s each)."""

    @classmethod
    def setUpClass(cls):
        open_db(":memory:")

    def setUp(self):
        self.snaps = [snap([row(row_id="a", tracking_number="A", order_name="#1", shipped_at=ago(10))])]
        self.builds = 0
        self._snapshot, self._build = board.snapshot, board.build
        board.snapshot = lambda force=False: self.snaps[-1]

        def counting_build(*a, **kw):
            self.builds += 1
            return self._build(*a, **kw)
        board.build = counting_build
        board.forget_built()

    def tearDown(self):
        board.snapshot, board.build = self._snapshot, self._build
        board.forget_built()

    @staticmethod
    def wait_for_background_builds():
        import threading
        for t in threading.enumerate():
            if t.name.startswith("shipping-board-build-"):
                t.join(5)

    def test_one_build_serves_every_request_until_something_changes(self):
        first = board.dataset("all")
        self.assertIs(board.dataset("all"), first)
        self.assertIs(board.dataset(None), first)                       # None is the "all" board
        self.assertEqual(self.builds, 1)
        board.dataset("ridhi")                                          # each brand has its own board
        self.assertEqual(self.builds, 2)
        self.snaps.append(snap([row(row_id="b", tracking_number="B", order_name="#2", shipped_at=ago(1))]))
        self.assertIs(board.dataset("all"), first)                      # a reloaded snapshot: the old board answers ...
        self.wait_for_background_builds()
        self.assertEqual(self.builds, 3)                                # ... while a new one is built in the background
        second = board.dataset("all")
        self.assertIsNot(second, first)
        self.assertIs(second.snap, self.snaps[-1])
        board.forget_built()                                            # a team mark or outcome: the page waits for it
        self.assertIsNot(board.dataset("all"), second)
        self.assertEqual(self.builds, 4)

    def test_an_old_build_is_not_reused_forever(self):
        first = board.dataset("all")
        key = "all"
        at, sn, ds = board._built[key]
        board._built[key] = (at - board.BUILT_SECONDS - 1, sn, ds)
        self.assertIs(board.dataset("all"), first)                      # answers at once, rebuilds in the background
        self.wait_for_background_builds()
        self.assertIsNot(board.dataset("all"), first)
        self.assertEqual(self.builds, 2)

    def test_a_build_started_before_a_team_mark_is_not_kept(self):
        def late_build(key, snap):
            board.forget_built()                                        # a team mark lands while this build runs
            return self._build(key, snap=snap)
        board.build = late_build
        self.assertIsNotNone(board.dataset("all"))                      # the request still gets an answer ...
        self.assertNotIn("all", board._built)                           # ... but the next one builds with the mark

    def test_reports_are_worked_out_once_per_board(self):
        ds = board.dataset("all")
        calls = []
        real = board.journey
        board.journey = lambda d: calls.append(1) or real(d)
        try:
            a = board.summary(ds)
            self.assertIs(board.summary(ds), a)
            self.assertEqual(len(calls), 1)
            self.assertIs(board.checks(ds), board.checks(ds))
            self.assertIsNot(board.analytics(ds, 30), board.analytics(ds, 90))   # each period has its own figures
            ds.memo.clear()                                             # what annotate() does after editing the board
            self.assertIsNot(board.summary(ds), a)
            self.assertEqual(len(calls), 2)
        finally:
            board.journey = real

    def test_parallel_requests_wait_for_one_build(self):
        import threading
        out = []
        threads = [threading.Thread(target=lambda: out.append(board.dataset("all"))) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.builds, 1)
        self.assertTrue(all(x is out[0] for x in out))


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
