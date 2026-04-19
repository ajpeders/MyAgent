import unittest
from unittest.mock import patch

import api


class ApiTests(unittest.TestCase):
    @patch("api.build_mail_system", return_value="mail system")
    @patch("api.build_messages", return_value=[{"role": "system", "content": "system"}])
    @patch("api.execute_noninteractive", return_value=[{"type": "answer", "content": "4"}])
    def test_create_chat_response_uses_default_model(self, _execute, _build_messages, _build_mail_system):
        status, body = api.create_chat_response("what is 2 + 2?")

        self.assertEqual(status, 200)
        self.assertEqual(body["model"], api.DEFAULT_MODEL)
        self.assertEqual(body["events"], [{"type": "answer", "content": "4"}])

    def test_create_chat_response_rejects_empty_prompt(self):
        status, body = api.create_chat_response("   ")

        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "prompt is required"})


if __name__ == "__main__":
    unittest.main()
