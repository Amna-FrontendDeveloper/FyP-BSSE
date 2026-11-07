import importlib
import os
import unittest
from unittest.mock import patch


class TestAIService(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_returns_fallback(self):
        import services.ai_service as ai_service

        importlib.reload(ai_service)

        success, result = ai_service.get_ai_response('hello')
        self.assertFalse(success)
        self.assertIn('API key', result)


if __name__ == '__main__':
    unittest.main()
