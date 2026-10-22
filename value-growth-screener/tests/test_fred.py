import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from vgs.cli import main
from vgs.data.cache import DataStore
from vgs.data.factors import FredClient, FredUnavailable

FAKE_KEY = "k" * 32  # low-entropy placeholder, never a real key
# Shape of what api.stlouisfed.org returned on 2026-10-22: HTTP 200, text/html, maintenance page.
MAINTENANCE = (b'<!doctype html>\n<html lang="en">\n<head>\n    <title>Site Maintenance | St. Louis Fed</title>\n'
               b'</head><body>We are performing maintenance.</body></html>')


class FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self.body, self.headers = body, {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def respond(body: bytes, content_type: str):
    return mock.patch("urllib.request.urlopen", return_value=FakeResponse(body, content_type))


class FredTests(unittest.TestCase):
    def test_maintenance_page_fails_clearly_without_leaking_the_key(self):
        with TemporaryDirectory() as tmp, respond(MAINTENANCE, "text/html; charset=utf-8"):
            client = FredClient(DataStore(tmp), api_key=FAKE_KEY)
            with self.assertRaises(FredUnavailable) as caught:
                client.observations("DGS10", "2026-06-01", "2026-09-01", "2026-09-01")
            message = str(caught.exception)
            self.assertIn("Site Maintenance | St. Louis Fed", message)
            self.assertIn("text/html", message)
            self.assertNotIn(FAKE_KEY, message)
            self.assertFalse(list((Path(tmp) / "cache").glob("*.json")) if (Path(tmp) / "cache").exists() else [])

    def test_valid_json_is_parsed_and_cached(self):
        body = json.dumps({"observations": [{"date": "2026-08-29", "value": "4.21"},
                                            {"date": "2026-08-30", "value": "."}]}).encode()
        with TemporaryDirectory() as tmp:
            client = FredClient(DataStore(tmp), api_key=FAKE_KEY)
            with respond(body, "application/json"):
                rows = client.observations("DGS10", "2026-08-01", "2026-09-01", "2026-09-01")
            self.assertEqual([r["value"] for r in rows], [4.21, None])
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("cache not used")):
                again = client.observations("DGS10", "2026-08-01", "2026-09-01", "2026-09-01")
            self.assertEqual(again, rows)

    def test_json_without_observations_is_an_error(self):
        body = json.dumps({"error_code": 400, "error_message": "Bad Request."}).encode()
        with TemporaryDirectory() as tmp, respond(body, "application/json"):
            with self.assertRaises(FredUnavailable) as caught:
                FredClient(DataStore(tmp), api_key=FAKE_KEY).observations("DGS10", "a", "b", "c")
            self.assertIn("Bad Request.", str(caught.exception))

    def _run_cli(self, github: bool):
        env = {"FRED_API_KEY": FAKE_KEY, "GITHUB_ACTIONS": "true" if github else ""}
        out, err = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as tmp, respond(MAINTENANCE, "text/html"), \
                mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["fred", "--series", "DGS10", "--start", "2026-06-01", "--end", "2026-09-01",
                         "--vintage-date", "2026-09-01", "--data-root", tmp])
        return code, out.getvalue(), err.getvalue()

    def test_cli_reports_one_line_and_exit_1(self):
        code, out, err = self._run_cli(github=False)
        self.assertEqual(code, 1)
        self.assertIn("may be under maintenance", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn(FAKE_KEY, out + err)

    def test_cli_on_github_prints_an_error_annotation(self):
        code, out, _ = self._run_cli(github=True)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("::error title=FRED::FRED DGS10: expected JSON"), out)


if __name__ == "__main__":
    unittest.main()
