import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import paratranz_sync as sync


class ParaTranzApiTests(unittest.TestCase):
    def test_requests_authenticate_with_bearer_for_raw_and_prefixed_tokens(self):
        for token in ("test-token", " Bearer test-token\n", "bearer test-token"):
            with self.subTest(token=token):
                response = io.BytesIO(json.dumps([{"key": "hello"}]).encode())
                with patch.object(sync, "urlopen", return_value=response) as request:
                    result = sync.api_request("GET", "/projects/15018/strings", token)
                self.assertEqual(result, [{"key": "hello"}])
                self.assertEqual(request.call_args.args[0].get_header("Authorization"),
                                 "Bearer test-token")

    def test_auth_failure_is_not_retried_and_does_not_print_response_body(self):
        error = HTTPError("https://paratranz.cn/api/projects/15018/strings", 401,
                          "Unauthorized", {}, io.BytesIO(b"sensitive response"))
        self.addCleanup(error.close)
        with patch.object(sync, "urlopen", side_effect=error) as request, \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(HTTPError):
                sync.api_request("GET", "/projects/15018/strings", "test-token")
        self.assertEqual(request.call_count, 1)
        self.assertIn("Renew PARATRANZ_TOKEN", stderr.getvalue())
        self.assertNotIn("sensitive response", stderr.getvalue())
        self.assertNotIn("test-token", stderr.getvalue())

    def test_exhausted_rate_limit_fails_instead_of_returning_empty_translations(self):
        error = HTTPError("https://paratranz.cn/api/projects/15018/strings", 429,
                          "Too Many Requests", {}, io.BytesIO(b""))
        self.addCleanup(error.close)
        with patch.object(sync, "urlopen", side_effect=error) as request, \
                patch.object(sync.time, "sleep") as sleep, \
                patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(HTTPError):
                sync.get_pt_strings("test-token", 2954203)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
