import os
import tempfile
import unittest
from datetime import date, timedelta

import database.database as db


class TestDailyUsageLimit(unittest.TestCase):
    def setUp(self):
        # Fresh temporary database per test — never touches your real app.db.
        self.temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_file.close()
        db.DATABASE_PATH = self.temp_db_file.name
        db.init_db()
        self.user_id = db.get_or_create_guest_user()

    def tearDown(self):
        os.remove(self.temp_db_file.name)

    def test_1_first_message_starts_at_zero(self):
        self.assertEqual(db.get_today_message_count(self.user_id), 0)
        self.assertFalse(db.has_reached_daily_limit(self.user_id))

    def test_2_normal_usage_increments_correctly(self):
        for _ in range(5):
            db.increment_usage(self.user_id)
        self.assertEqual(db.get_today_message_count(self.user_id), 5)

    def test_3_99th_message_is_allowed(self):
        for _ in range(98):
            db.increment_usage(self.user_id)
        # count is now 98 -> the 99th attempt should still be allowed
        self.assertFalse(db.has_reached_daily_limit(self.user_id))

    def test_4_100th_message_is_allowed(self):
        for _ in range(99):
            db.increment_usage(self.user_id)
        # count is now 99 -> the 100th attempt should still be allowed
        self.assertFalse(db.has_reached_daily_limit(self.user_id))
        db.increment_usage(self.user_id)
        self.assertEqual(db.get_today_message_count(self.user_id), 100)

    def test_5_101st_message_is_blocked(self):
        for _ in range(100):
            db.increment_usage(self.user_id)
        # count is now 100 -> the 101st attempt must be blocked
        self.assertTrue(db.has_reached_daily_limit(self.user_id))

    def test_6_usage_resets_on_next_day(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        connection = db.get_db_connection()
        connection.execute(
            "INSERT INTO usage (user_id, date, message_count) VALUES (?, ?, ?)",
            (self.user_id, yesterday, 100),
        )
        connection.commit()
        connection.close()

        # Today's count is a separate row — yesterday's 100 shouldn't carry over.
        self.assertEqual(db.get_today_message_count(self.user_id), 0)
        self.assertFalse(db.has_reached_daily_limit(self.user_id))


if __name__ == "__main__":
    unittest.main()