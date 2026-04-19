import unittest
import config


class ConfigTests(unittest.TestCase):
    def test_default_model_is_router_friendly(self):
        self.assertEqual(config.DEFAULT_MODEL, "qwen2.5:3b")


if __name__ == "__main__":
    unittest.main()
