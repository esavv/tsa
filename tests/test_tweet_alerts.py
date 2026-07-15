import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import run_tweet_alerts as alerts


def row(
    airport="JFK",
    terminal="5",
    gate="",
    wait_minutes=45,
    wait_min_minutes=None,
    wait_max_minutes=None,
):
    return {
        "airport": airport,
        "terminal": terminal,
        "gate": gate,
        "queue_type": "general",
        "wait_minutes": wait_minutes,
        "wait_min_minutes": wait_min_minutes,
        "wait_max_minutes": wait_max_minutes,
    }


class TweetAlertTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "JFK": {
                "code": "JFK",
                "terminal_tab": {
                    "without_gate": "Terminal {terminal}",
                    "with_gate": "Terminal {terminal}: Gates {gate}",
                },
                "wait_times_ui": {"chip": "absolute"},
                "tweet_alerts": {"enabled": True},
            },
            "CLT": {
                "code": "CLT",
                "terminal_tab": {
                    "ignore_gate": True,
                    "without_gate": "{terminal}",
                    "with_gate": "{terminal}: {gate}",
                },
                "wait_times_ui": {"chip": "absolute"},
            },
        }

    def test_uses_unique_terminal_and_gate_chart_target(self):
        candidates = alerts.candidates_for_rows(
            [
                row(terminal="4", gate="A", wait_minutes=46),
                row(terminal="4", gate="B", wait_minutes=61),
            ],
            self.catalog,
        )

        self.assertEqual(2, len(candidates))
        self.assertEqual({"A", "B"}, {candidate.target.gate for candidate in candidates})
        self.assertEqual({45, 60}, {candidate.threshold for candidate in candidates})

    def test_collapses_gate_when_webapp_ignores_gate(self):
        candidates = alerts.candidates_for_rows(
            [
                row(airport="CLT", terminal="Checkpoint 1", gate="A", wait_minutes=46),
                row(airport="CLT", terminal="Checkpoint 1", gate="B", wait_minutes=62),
            ],
            self.catalog,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("", candidates[0].target.gate)
        self.assertEqual(60, candidates[0].threshold)
        self.assertEqual(62, candidates[0].wait_minutes)

    def test_groups_same_airport_targets_and_links_first_by_wait(self):
        candidates = alerts.candidates_for_rows(
            [
                row(terminal="4", gate="A", wait_minutes=46),
                row(terminal="5", gate="", wait_minutes=61),
            ],
            self.catalog,
        )

        posts = alerts.posts_for_candidates("2026-07-14T20:00:00Z", candidates)

        self.assertEqual(1, len(posts))
        self.assertEqual(2, len(posts[0].candidates))
        self.assertEqual(
            "https://tsa-times.com/jfk?terminal=5",
            posts[0].url,
        )
        self.assertIn("Terminal 4: Gates A: 46 min", posts[0].text)
        self.assertIn("Terminal 5: 61 min", posts[0].text)

    def test_cooldown_suppresses_same_threshold(self):
        candidate = alerts.candidates_for_rows([row(wait_minutes=49)], self.catalog)[0]
        now = datetime(2026, 7, 14, 20, tzinfo=timezone.utc)
        state = {candidate.target: (now - timedelta(hours=2), 45)}

        self.assertEqual([], alerts.eligible_candidates([candidate], now, state))

    def test_higher_threshold_overrides_and_restarts_cooldown(self):
        now = datetime(2026, 7, 14, 20, tzinfo=timezone.utc)
        at_45 = alerts.candidates_for_rows([row(wait_minutes=49)], self.catalog)[0]
        at_60 = alerts.candidates_for_rows([row(wait_minutes=61)], self.catalog)[0]
        state = {at_45.target: (now - timedelta(hours=2), 45)}

        self.assertEqual([at_60], alerts.eligible_candidates([at_60], now, state))
        state[at_60.target] = (now, at_60.threshold)
        self.assertEqual(
            [],
            alerts.eligible_candidates([at_60], now + timedelta(hours=5), state),
        )
        self.assertEqual(
            [at_60],
            alerts.eligible_candidates([at_60], now + timedelta(hours=6), state),
        )

    def test_range_airport_uses_displayed_upper_bound(self):
        catalog = {
            "JFK": {
                **self.catalog["JFK"],
                "wait_times_ui": {"chip": "range"},
            }
        }
        candidate = alerts.candidates_for_rows(
            [
                row(
                    wait_minutes=None,
                    wait_min_minutes=40,
                    wait_max_minutes=47,
                )
            ],
            catalog,
        )[0]

        self.assertEqual(47, candidate.wait_minutes)
        self.assertEqual("40-47 min", candidate.wait_display)
        self.assertEqual(45, candidate.threshold)


if __name__ == "__main__":
    unittest.main()
