"""Unit tests for scraper closed / no-data → omit row behavior (SEA, LAX, ATL, DCA)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scraper  # noqa: E402


class TestParseWaitTextToFields(unittest.TestCase):
    def test_closed_and_unavailable_omit_signal(self) -> None:
        self.assertEqual(scraper.parse_wait_text_to_fields("CLOSED"), (None, None, None))
        self.assertEqual(scraper.parse_wait_text_to_fields("closed for cleaning"), (None, None, None))
        self.assertEqual(scraper.parse_wait_text_to_fields("Temporarily unavailable"), (None, None, None))

    def test_empty_omits_signal(self) -> None:
        self.assertEqual(scraper.parse_wait_text_to_fields(""), (None, None, None))
        self.assertEqual(scraper.parse_wait_text_to_fields("   "), (None, None, None))

    def test_numeric_waits_unchanged(self) -> None:
        self.assertEqual(scraper.parse_wait_text_to_fields("12"), (12, None, None))
        self.assertEqual(scraper.parse_wait_text_to_fields("3-7"), (None, 3, 7))
        self.assertEqual(scraper.parse_wait_text_to_fields("< 10"), (None, 0, 10))


class TestFetchSeaAirport(unittest.TestCase):
    def test_skips_not_open_or_no_data(self) -> None:
        payload = [
            {
                "Name": "Main",
                "IsOpen": True,
                "IsDataAvailable": True,
                "WaitTimeMinutes": 7,
                "CheckpointID": 1,
                "LastUpdated": None,
            },
            {
                "Name": "Closed Checkpoint",
                "IsOpen": False,
                "IsDataAvailable": True,
                "WaitTimeMinutes": 0,
                "CheckpointID": 2,
                "LastUpdated": None,
            },
            {
                "Name": "No Data",
                "IsOpen": True,
                "IsDataAvailable": False,
                "WaitTimeMinutes": 0,
                "CheckpointID": 3,
                "LastUpdated": None,
            },
        ]
        with patch.object(scraper, "fetch_json_url", return_value=payload):
            rows = scraper.fetch_sea_airport()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["wait_minutes"], 7)
        self.assertEqual(rows[0]["terminal"], "Main")


class TestFetchDcaAirport(unittest.TestCase):
    def test_omits_missing_waittime_and_closed_text(self) -> None:
        payload = {
            "response": {
                "res": {
                    "a": {
                        "location": "Terminal 2",
                        "isDisabled": 0,
                        "waittime": None,
                        "pre_disabled": 1,
                    },
                    "b": {
                        "location": "Terminal 2",
                        "isDisabled": 0,
                        "waittime": "Closed",
                        "pre_disabled": 1,
                    },
                    "c": {
                        "location": "Terminal 2",
                        "isDisabled": 0,
                        "waittime": "15",
                        "pre_disabled": 1,
                    },
                }
            }
        }
        with patch.object(scraper, "fetch_json_url", return_value=payload):
            rows = scraper.fetch_dca_airport()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["wait_minutes"], 15)
        self.assertEqual(rows[0]["queue_type"], "general")

    def test_omits_blank_pre_and_keeps_numeric_pre(self) -> None:
        payload = {
            "response": {
                "res": {
                    "x": {
                        "location": "Terminal A",
                        "isDisabled": 1,
                        "pre_disabled": 0,
                        "pre": "   ",
                    },
                    "y": {
                        "location": "Terminal B",
                        "isDisabled": 1,
                        "pre_disabled": 0,
                        "pre": "8",
                    },
                }
            }
        }
        with patch.object(scraper, "fetch_json_url", return_value=payload):
            rows = scraper.fetch_dca_airport()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["queue_type"], "precheck")
        self.assertEqual(rows[0]["wait_minutes"], 8)


if __name__ == "__main__":
    unittest.main()
