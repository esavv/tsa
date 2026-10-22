#!/usr/bin/env python3
"""Tests for transport fallbacks used by Mobi wait-time sources."""

import unittest
import urllib.error
from unittest.mock import call, patch

from scripts import scraper


def _payload(name: str) -> dict:
    return {
        "data": {
            "wait_times": [
                {
                    "id": "1",
                    "lane": "general",
                    "name": name,
                    "isOpen": True,
                    "isDisplayable": True,
                    "waitSeconds": 120,
                    "lastUpdatedTimestamp": 1_792_631_054,
                    "attributes": {},
                }
            ]
        },
        "status": {"code": 200, "message": ""},
    }


class TestMobiFallbacks(unittest.TestCase):
    @patch("scripts.scraper._fetch_mobi_checkpoint_json")
    def test_dfw_retries_transport_failure_through_proxy(self, fetch):
        fetch.side_effect = [urllib.error.URLError("unreachable"), _payload("A21")]

        rows = scraper.fetch_dfw_airport()

        self.assertEqual(rows[0]["terminal"], "A")
        self.assertEqual(
            fetch.call_args_list,
            [
                call(
                    scraper.DFW_WAIT_TIMES_URL,
                    scraper.DFW_MOBILE_API_KEY,
                    scraper.DFW_MOBILE_API_VERSION,
                ),
                call(
                    scraper.DFW_WAIT_TIMES_URL,
                    scraper.DFW_MOBILE_API_KEY,
                    scraper.DFW_MOBILE_API_VERSION,
                    use_proxy=True,
                ),
            ],
        )

    @patch("scripts.scraper._fetch_mobi_checkpoint_json")
    def test_mco_retries_transport_failure_on_acceptance_api(self, fetch):
        fetch.side_effect = [urllib.error.URLError("refused"), _payload("South")]

        rows = scraper.fetch_mco_airport()

        self.assertEqual(rows[0]["terminal"], "South")
        self.assertEqual(
            fetch.call_args_list,
            [
                call(
                    scraper.MCO_WAIT_TIMES_URL,
                    scraper.MCO_MOBILE_API_KEY,
                    scraper.MCO_MOBILE_API_VERSION,
                ),
                call(
                    scraper.MCO_FALLBACK_WAIT_TIMES_URL,
                    scraper.MCO_MOBILE_API_KEY,
                    scraper.MCO_MOBILE_API_VERSION,
                ),
            ],
        )

    @patch("scripts.scraper._fetch_mobi_checkpoint_json")
    def test_mco_does_not_mask_api_errors(self, fetch):
        fetch.side_effect = ValueError("bad payload")

        with self.assertRaisesRegex(ValueError, "bad payload"):
            scraper.fetch_mco_airport()

        fetch.assert_called_once_with(
            scraper.MCO_WAIT_TIMES_URL,
            scraper.MCO_MOBILE_API_KEY,
            scraper.MCO_MOBILE_API_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
