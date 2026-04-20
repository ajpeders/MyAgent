import unittest
import os
from core import config


class ConfigTests(unittest.TestCase):
    def test_default_model_uses_env_with_qwen3_fallback(self):
        self.assertEqual(config.DEFAULT_MODEL, os.environ.get("LLM_MODEL", "qwen3:8b"))


if __name__ == "__main__":
    unittest.main()
