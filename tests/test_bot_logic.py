import unittest

import bot


class BotWorkflowLogicTests(unittest.TestCase):
    def test_custom_deadline_uses_24_hour_format(self):
        parsed = bot.parse_deadline("30.07.2026 18:00")
        self.assertIsNotNone(parsed)
        self.assertTrue(bot.format_deadline(parsed).endswith("30.07.2026 18:00"))

    def test_invalid_12_hour_deadline_is_rejected(self):
        self.assertIsNone(bot.parse_deadline("30.07.2026 6 PM"))

    def test_username_is_used_for_group_mention(self):
        self.assertEqual(
            bot.user_mention({"tg_id": 1, "full_name": "Test User", "username": "tester"}),
            "@tester",
        )

    def test_user_id_link_is_fallback_without_username(self):
        mention = bot.user_mention({"tg_id": 1, "full_name": "Test User", "username": None})
        self.assertIn("tg://user?id=1", mention)


if __name__ == "__main__":
    unittest.main()
