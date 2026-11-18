"""Daily copy of the MCF tracking sheet into Supabase: schedule (09:00 IST), the copy itself, run logging."""
import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from flowmerce.modules.shipping import mcf_sync
from flowmerce.modules.shipping.supabase import SupabaseError


def utc(*a):
    return datetime(*a, tzinfo=UTC)


PKG = {"sfo_id": "SHOP-RBP8870-1", "store": "RBP", "displayable_order_id": "8870", "order_status": "Complete",
       "received_at": "2026-11-10", "speed": "Standard", "package_number": "303162654", "tracking_number": "TBA1",
       "carrier_code": "Amazon Logistics", "shipped_at": "2026-11-11", "estimated_arrival": "2026-11-14",
       "tracking_status": "DELIVERED", "tracking_status_text": "Package delivered.", "delivered_at": "2026-11-13T20:40:00Z",
       "last_event_at": "2026-11-13T20:40:00Z", "last_event_city": "Austin", "last_event_state": "TX",
       "sheet_flag": "Delivered", "fetched_at": "2026-11-17T22:18:00+00:00", "events": [], "_source": "sheet"}


class ScheduleTest(unittest.TestCase):
    def test_nine_am_ist(self):
        self.assertEqual(mcf_sync.due_at(datetime(2026, 11, 18).date()), utc(2026, 11, 18, 3, 30))   # 09:00 IST
        with mock.patch.dict(os.environ, {"AMAZON_MCF_SYNC_AT": "10:15"}):
            self.assertEqual(mcf_sync.sync_time(), (10, 15))
        with mock.patch.dict(os.environ, {"AMAZON_MCF_SYNC_AT": "nonsense"}):
            self.assertEqual(mcf_sync.sync_time(), (9, 0))

    def test_next_run(self):
        # before 09:00 IST: wait for it, even if yesterday's copy is missing (the sheet is not ready before ~05:00)
        self.assertEqual(mcf_sync.next_run(utc(2026, 11, 18, 2, 0), utc(2026, 11, 16, 3, 31)), utc(2026, 11, 18, 3, 30))
        # after 09:00 IST with no copy since: at once (server was off at 09:00)
        self.assertEqual(mcf_sync.next_run(utc(2026, 11, 18, 6, 0), utc(2026, 11, 17, 3, 31)), utc(2026, 11, 18, 6, 0))
        self.assertEqual(mcf_sync.next_run(utc(2026, 11, 18, 6, 0), None), utc(2026, 11, 18, 6, 0))
        # after 09:00 IST and today's copy done: tomorrow 09:00 IST
        self.assertEqual(mcf_sync.next_run(utc(2026, 11, 18, 6, 0), utc(2026, 11, 18, 3, 31)), utc(2026, 11, 19, 3, 30))
        # 23:00 UTC is already the next day in India (04:30 IST): wait for that day's 09:00 IST
        self.assertEqual(mcf_sync.next_run(utc(2026, 11, 18, 23, 0), utc(2026, 11, 18, 3, 31)), utc(2026, 11, 19, 3, 30))


class SyncTest(unittest.TestCase):
    def fake(self):
        c = mock.Mock()
        c.insert_returning.return_value = {"id": 7}
        return c

    def test_copies_rows_without_names_and_logs_the_run(self):
        c = self.fake()
        with mock.patch.object(mcf_sync, "client", return_value=c), mock.patch.object(mcf_sync.mcf_sheet, "load", return_value=[PKG, dict(PKG)]):
            res = mcf_sync.sync("job:x")
        self.assertEqual((res["state"], res["rows"]), ("ok", 1))                     # same MCF id + parcel = one row
        table, rows, key = c.upsert.call_args[0]
        self.assertEqual((table, key), ("amazon_mcf_sheet", "sfo_id,package_key"))
        r = rows[0]
        self.assertEqual((r["package_key"], r["order_number"], r["received_on"], r["checked_at"]),
                         ("303162654", "8870", "2026-11-10", "2026-11-17T22:18:00+00:00"))
        self.assertNotIn("first_synced_at", r)                                        # kept from the first copy
        self.assertEqual(c.insert_returning.call_args[0][1]["source"], "amazon")
        self.assertEqual(c.update.call_args[0][2]["status"], "ok")
        self.assertEqual(c.update.call_args[0][2]["rows_written"], 1)

    def test_unreadable_sheet_is_a_failed_run(self):
        c = self.fake()
        with mock.patch.object(mcf_sync, "client", return_value=c), mock.patch.object(mcf_sync.mcf_sheet, "load", return_value=None), \
             mock.patch.object(mcf_sync.mcf_sheet, "status", return_value={"error": "The MCF sheet is not shared."}):
            res = mcf_sync.sync("job:x")
        self.assertEqual(res["state"], "failed")
        c.upsert.assert_not_called()
        self.assertEqual(c.update.call_args[0][2]["status"], "failed")
        self.assertIn("not shared", c.update.call_args[0][2]["error"])

    def test_crash_never_leaves_the_run_running(self):
        c = self.fake()
        c.upsert.side_effect = RuntimeError("boom")
        with mock.patch.object(mcf_sync, "client", return_value=c), mock.patch.object(mcf_sync.mcf_sheet, "load", return_value=[PKG]):
            with self.assertRaises(RuntimeError):
                mcf_sync.sync("job:x")
        self.assertEqual(c.update.call_args[0][2]["status"], "failed")

    def test_already_running_and_stale_run(self):
        c = self.fake()
        c.insert_returning.side_effect = [SupabaseError("conflict", "running"), SupabaseError("conflict", "running")]
        with mock.patch.object(mcf_sync, "client", return_value=c):
            self.assertEqual(mcf_sync.sync("job:x")["state"], "already_running")
        stale_filter = c.update.call_args[0][1]
        self.assertIn(("status", "eq.running"), stale_filter)                        # an interrupted run is ended first
        c = self.fake()
        c.insert_returning.side_effect = [SupabaseError("conflict", "running"), {"id": 8}]
        with mock.patch.object(mcf_sync, "client", return_value=c), mock.patch.object(mcf_sync.mcf_sheet, "load", return_value=[PKG]):
            self.assertEqual(mcf_sync.sync("job:x")["state"], "ok")


if __name__ == "__main__":
    unittest.main()
