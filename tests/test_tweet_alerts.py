import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO

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

        posts = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z", candidates, link_available=True
        )

        self.assertEqual(1, len(posts))
        self.assertEqual(2, len(posts[0].candidates))
        self.assertEqual(
            "https://tsa-times.com/jfk?terminal=5",
            posts[0].url,
        )
        self.assertIn("Terminal 4: Gates A: 46 min", posts[0].text)
        self.assertIn("Terminal 5: 61 min", posts[0].text)

    def test_single_target_tweet_uses_one_line_headline(self):
        candidate = alerts.candidates_for_rows([row(wait_minutes=57)], self.catalog)

        post = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z", candidate, link_available=True
        )[0]

        self.assertTrue(
            post.text.startswith(
                "TSA wait times are elevated at JFK Terminal 5: 57 min"
            )
        )
        self.assertNotIn("JFK:\n\nTerminal", post.text)

    def test_text_only_post_omits_url(self):
        candidate = alerts.candidates_for_rows([row(wait_minutes=57)], self.catalog)

        post = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z", candidate, link_available=False
        )[0]

        self.assertFalse(post.included_link)
        self.assertNotIn("https://", post.text)
        self.assertNotIn("tsa-times.com", post.text)

    def test_only_first_same_scrape_post_receives_available_link(self):
        candidates = alerts.candidates_for_rows(
            [
                row(wait_minutes=57),
                row(
                    airport="CLT",
                    terminal="Checkpoint 1",
                    wait_minutes=61,
                ),
            ],
            self.catalog,
        )

        posts = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z", candidates, link_available=True
        )

        self.assertEqual(2, len(posts))
        self.assertEqual(1, sum(post.included_link for post in posts))

    def test_generated_post_id_is_stable_and_content_specific(self):
        first = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z",
            alerts.candidates_for_rows([row(wait_minutes=57)], self.catalog),
            link_available=True,
        )[0]
        same = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z",
            alerts.candidates_for_rows([row(wait_minutes=57)], self.catalog),
            link_available=True,
        )[0]
        changed = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z",
            alerts.candidates_for_rows([row(wait_minutes=58)], self.catalog),
            link_available=True,
        )[0]

        self.assertEqual(first.post_id, same.post_id)
        self.assertNotEqual(first.post_id, changed.post_id)
        self.assertRegex(
            first.post_id,
            r"^20260714T200000Z-JFK-[0-9a-f]{12}$",
        )

    def test_summary_counts_posts_by_airport(self):
        first = alerts.posts_for_candidates(
            "2026-07-14T20:00:00Z",
            alerts.candidates_for_rows([row(wait_minutes=57)], self.catalog),
            link_available=True,
        )[0]
        later = alerts.posts_for_candidates(
            "2026-07-15T02:00:00Z",
            alerts.candidates_for_rows([row(wait_minutes=61)], self.catalog),
            link_available=False,
        )[0]
        output = StringIO()

        with redirect_stdout(output):
            alerts.print_summary([first, later], 7)

        self.assertIn("Projected tweets: 2 over 7 days", output.getvalue())
        self.assertIn("Link posts: 1", output.getvalue())
        self.assertIn("Text-only posts: 1", output.getvalue())
        self.assertIn("JFK  2", output.getvalue())

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
