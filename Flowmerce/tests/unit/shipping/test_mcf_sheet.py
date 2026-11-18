"""The Amazon MCF tracking sheet reader: column mapping, order numbers (never customer names), dates, fallback."""
import unittest
from datetime import UTC, datetime
from unittest import mock

from flowmerce.modules.shipping import amazon_mcf, board, mcf_sheet

NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
HEAD = ["Flag", "Brand", "Order", "MCF id", "Order status", "Received", "Speed", "Parcel", "Carrier", "Tracking", "Shipped",
        "Arrives by", "Now", "Last scan", "Last scan at (IST)", "Where", "Delivered (IST)", "Checked (IST)", "Link", "_key",
        "_pass", "_lastIso"]


def line(**kw):
    base = {"Flag": "Delivered", "Brand": "Ridhi", "Order": "RBP8870", "MCF id": "SHOP-RBP8870-1", "Order status": "Complete",
            "Received": "2026-11-10", "Speed": "Standard", "Parcel": "303162654", "Carrier": "Amazon Logistics",
            "Tracking": "TBA327000000001", "Shipped": "2026-11-11", "Arrives by": "2026-11-14", "Now": "DELIVERED",
            "Last scan": "Package delivered.", "Last scan at (IST)": "14 Nov 02:10", "Where": "Austin, TX, US",
            "Delivered (IST)": "14 Nov 02:10", "Checked (IST)": "18 Nov 03:48", "Link": "https://track.amazon.com/x",
            "_key": "k", "_pass": "1", "_lastIso": "2026-11-13T20:40:00Z"}
    base.update(kw)
    return [base[h] for h in HEAD]


class SheetParseTest(unittest.TestCase):
    def test_columns_map_to_packages(self):
        p = mcf_sheet.parse([HEAD, line()], now=NOW)[0]
        self.assertEqual((p["store"], p["displayable_order_id"], p["tracking_number"], p["tracking_status"]),
                         ("RBP", "8870", "TBA327000000001", "DELIVERED"))
        self.assertEqual((p["delivered_at"], p["last_event_city"], p["last_event_state"]), ("2026-11-13T20:40:00Z", "Austin", "TX"))
        self.assertEqual(p["fetched_at"], "2026-11-17T22:18:00+00:00")       # 18 Nov 03:48 IST
        self.assertEqual((p["shipped_at"], p["estimated_arrival"], p["_source"]), ("2026-11-11", "2026-11-14", "sheet"))
        self.assertEqual(amazon_mcf._carrier(p["carrier_code"]), "Amazon Logistics US")

    def test_order_numbers_never_names(self):
        on = mcf_sheet.order_number
        self.assertEqual([on("RBP8870"), on("Shopify #8608 1"), on("8306"), on("Shopify # RBP7999 1"), on("x", "SHOP-RBP8862-1")],
                         ["8870", "8608", "8306", "7999", "8862"])
        self.assertIsNone(on("Pamela Davis4", "Pamela Davis4"))   # a customer's name with a digit is not order #4
        self.assertIsNone(on("4229819659"))                       # another channel's long id
        rows = mcf_sheet.parse([HEAD, line(Order="Sofi Moon", **{"MCF id": "Sofi Moon"})], now=NOW)
        self.assertIsNone(rows[0]["displayable_order_id"])
        self.assertNotIn("Sofi", repr({k: v for k, v in rows[0].items() if k != "sfo_id"}))
        self.assertNotIn("track.amazon.com/x", repr(rows))         # links are not kept

    def test_columns_found_by_name_and_brand(self):
        head = list(reversed(HEAD))
        p = mcf_sheet.parse([head, list(reversed(line(Brand="CPC", Order="8306", **{"MCF id": "#8306"})))], now=NOW)[0]
        self.assertEqual((p["store"], p["displayable_order_id"]), ("CPC", "8306"))
        with self.assertRaises(ValueError):
            mcf_sheet.parse([["Something"], ["x"]], now=NOW)

    def test_not_shipped_yet(self):
        p = mcf_sheet.parse([HEAD, line(**{"Order status": "Planning", "Parcel": "", "Carrier": "", "Tracking": "", "Shipped": "",
                                           "Now": "", "Last scan": "", "_lastIso": "", "Delivered (IST)": ""})], now=NOW)[0]
        self.assertEqual((p["shipment_status"], p["tracking_number"], p["delivered_at"]), (None, None, None))

    def test_ist_year_rollover(self):
        self.assertTrue(mcf_sheet._ist("31 Dec 23:00", datetime(2027, 1, 2, tzinfo=UTC)).startswith("2026-12-31"))


class LoadTest(unittest.TestCase):
    def test_page_reads_supabase_only(self):
        c = mock.Mock()
        c.select.return_value = mock.Mock(rows=[{"sfo_id": "a", "source": "sheet"}])
        with mock.patch.object(amazon_mcf, "client", return_value=c), mock.patch.object(mcf_sheet, "load") as sheet:
            self.assertEqual(amazon_mcf.load()[0]["_source"], "sheet")
            sheet.assert_not_called()                                   # never the sheet on a page load
        self.assertIn("source", c.select.call_args[0][1][0][1])

    def test_works_before_111_and_without_109(self):
        from flowmerce.modules.shipping.supabase import SupabaseError
        c = mock.Mock()
        c.select.side_effect = [SupabaseError("schema_missing", "column source does not exist"), mock.Mock(rows=[{"sfo_id": "a"}])]
        with mock.patch.object(amazon_mcf, "client", return_value=c):
            self.assertEqual(amazon_mcf.load()[0]["_source"], "amazon_api")
        c.select.side_effect = SupabaseError("schema_missing", "relation does not exist")
        with mock.patch.object(amazon_mcf, "client", return_value=c):
            self.assertIsNone(amazon_mcf.load())

    def test_state_shows_daily_copy_and_why_it_failed(self):
        feeds = [{"source": "amazon", "kind": "import", "last_ok_at": "2026-11-17T03:31:00+00:00",
                  "last_attempt_at": "2026-11-18T03:30:00+00:00", "last_status": "failed",
                  "last_error": "The MCF sheet is not shared with Flowmerce's Google service account."}]
        with mock.patch.object(board, "service_account_email", return_value="reader@x.iam.gserviceaccount.com"):
            st = board.amazon_state(board.Snapshot([], feeds, NOW, mcf=[]))
        self.assertEqual((st["loaded"], st["sync"]["schedule"], st["serviceAccount"]),
                         (False, "Daily at 09:00 IST", "reader@x.iam.gserviceaccount.com"))
        self.assertIn("not shared", st["problem"])
        st = board.amazon_state(board.Snapshot([], [], NOW, mcf=[{"sfo_id": "a", "_source": "sheet", "tracking_status": "DELIVERED",
                                                                   "package_number": "1", "fetched_at": "2026-11-17T22:18:00+00:00"}]))
        self.assertEqual((st["source"], st["orders"], st["delivered"], st["problem"]), ("sheet", 1, 1, None))

    def test_reads_every_tab_with_mcf_columns_and_keeps_the_newest_copy(self):
        meta = mock.Mock(status_code=200, content=b"x")
        meta.json.return_value = {"sheets": [{"properties": {"title": "Tracking"}}, {"properties": {"title": "History"}},
                                             {"properties": {"title": "Notes"}}]}
        older = line(**{"Now": "IN_TRANSIT", "Checked (IST)": "10 Nov 03:48", "_lastIso": "2026-11-09T10:00:00Z"})
        newer = line(**{"Checked (IST)": "18 Nov 03:48"})
        old_order = line(Order="RBP7001", **{"MCF id": "SHOP-RBP7001-1", "Parcel": "111", "Tracking": "TBA700", "Received": "2026-09-12"})
        vals = mock.Mock(status_code=200, content=b"x")
        vals.json.return_value = {"valueRanges": [{"values": [HEAD, newer]}, {"values": [HEAD, older, old_order]},
                                                  {"values": [["Remarks"], ["call ERP"]]}]}
        with mock.patch("flowmerce.modules.seo.integrations.google._token", return_value="t"), \
             mock.patch.object(mcf_sheet.httpx, "get", side_effect=[meta, vals]) as get, \
             mock.patch.dict("os.environ", {"AMAZON_MCF_SHEET_TABS": "", "AMAZON_MCF_SHEET_TAB": ""}):
            rows = mcf_sheet.load()
        self.assertEqual(mcf_sheet.status()["tabs"], ["Tracking", "History"])          # "Notes" has no MCF columns
        by = {p["sfo_id"]: p for p in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by["SHOP-RBP8870-1"]["tracking_status"], "DELIVERED")         # the newer check wins
        self.assertEqual((by["SHOP-RBP7001-1"]["displayable_order_id"], by["SHOP-RBP7001-1"]["received_at"]), ("7001", "2026-09-12"))
        self.assertIn(("ranges", "'History'"), get.call_args_list[1].kwargs["params"])

    def test_tabs_can_be_named_in_env(self):
        with mock.patch.dict("os.environ", {"AMAZON_MCF_SHEET_TABS": "Tracking, Sept-Oct", "AMAZON_MCF_SHEET_TAB": ""}):
            self.assertEqual(mcf_sheet.sheet_tabs(), ["Tracking", "Sept-Oct"])
        with mock.patch.dict("os.environ", {"AMAZON_MCF_SHEET_TABS": "", "AMAZON_MCF_SHEET_TAB": ""}):
            self.assertIsNone(mcf_sheet.sheet_tabs())

    def test_unreadable_sheet_is_reported_not_raised(self):
        res = mock.Mock(status_code=403, content=b"x", reason_phrase="Forbidden")
        res.json.return_value = {"error": {"message": "The caller does not have permission"}}
        with mock.patch("flowmerce.modules.seo.integrations.google._token", return_value="t"), \
             mock.patch.object(mcf_sheet.httpx, "get", return_value=res):
            self.assertIsNone(mcf_sheet.load())
        self.assertIn("not shared", mcf_sheet.status()["error"])
        res.json.return_value = {"error": {"message": "Google Sheets API has not been used in project 1 before or it is disabled."}}
        with mock.patch("flowmerce.modules.seo.integrations.google._token", return_value="t"), \
             mock.patch.object(mcf_sheet.httpx, "get", return_value=res):
            mcf_sheet.load()
        self.assertIn("not enabled", mcf_sheet.status()["error"])


if __name__ == "__main__":
    unittest.main()
