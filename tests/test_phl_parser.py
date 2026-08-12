#!/usr/bin/env python3
"""Tests for the PHL checkpoint-hours parser."""

import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from scraper import PhlSchedule, _parse_phl_checkpoint_hours, _phl_schedule_is_open

# Current shape: entry keys quoted, properties bare, plus an optional `days`.
CURRENT_JS = """
  const tHours = {
    'tA': { open: '05:00', close: '22:15' },
    'tAw1': { open: '15:00', close: '17:30', days: [0, 1, 4, 5] },
    'tAe': { open: '04:15', close: '20:15' },
    'tAepre': { open: '04:15', close: '18:30' },
    'tB': { open: '03:30', close: '21:15' },
    'tC': { open: '04:15', close: '20:00' },
    'tDE': { open: '03:00', close: '22:45' },
    'tDEpre': { open: '03:45', close: '20:00' },
    'tF': { open: '04:30', close: '21:15' }
  };
"""

# Previous shape, with every property key quoted.
LEGACY_JS = """
  const tHours = {
    'tA': { 'open': '05:00', 'close': '22:15' },
    'tAe': { 'open': '04:15', 'close': '20:15' },
    'tAepre': { 'open': '04:15', 'close': '18:30' },
    'tB': { 'open': '03:30', 'close': '21:15' },
    'tC': { 'open': '04:15', 'close': '20:00' },
    'tDE': { 'open': '03:00', 'close': '22:45' },
    'tDEpre': { 'open': '03:45', 'close': '20:00' },
    'tF': { 'open': '04:30', 'close': '21:15' }
  };
"""


def _js_weekday_today() -> int:
    return datetime.now(ZoneInfo("America/New_York")).isoweekday() % 7


class TestPhlCheckpointHours(unittest.TestCase):
    def test_parses_bare_property_keys(self):
        hours = _parse_phl_checkpoint_hours(CURRENT_JS)
        self.assertEqual(hours["tA"].open_time, "05:00")
        self.assertEqual(hours["tA"].close_time, "22:15")
        self.assertIsNone(hours["tA"].days)

    def test_still_parses_quoted_property_keys(self):
        hours = _parse_phl_checkpoint_hours(LEGACY_JS)
        self.assertEqual(hours["tDE"].open_time, "03:00")
        self.assertEqual(hours["tDE"].close_time, "22:45")

    def test_parses_optional_days_list(self):
        hours = _parse_phl_checkpoint_hours(CURRENT_JS)
        self.assertEqual(hours["tAw1"].days, frozenset({0, 1, 4, 5}))

    def test_entry_with_days_does_not_break_neighbours(self):
        hours = _parse_phl_checkpoint_hours(CURRENT_JS)
        self.assertIn("tAe", hours)
        self.assertEqual(hours["tAe"].open_time, "04:15")

    def test_missing_mapped_entry_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _parse_phl_checkpoint_hours(
                "const tHours = { 'tA': { open: '05:00', close: '22:15' } };"
            )
        self.assertIn("missing tHours entries", str(ctx.exception))

    def test_no_block_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _parse_phl_checkpoint_hours("(function(){ var x = 1; })();")
        self.assertIn("missing tHours block", str(ctx.exception))


class TestPhlScheduleIsOpen(unittest.TestCase):
    def test_closed_when_today_is_excluded(self):
        others = frozenset(set(range(7)) - {_js_weekday_today()})
        hours = {"k": PhlSchedule("00:00", "23:59", others)}
        self.assertFalse(_phl_schedule_is_open(hours, "k"))

    def test_closed_when_open_equals_close(self):
        hours = {"k": PhlSchedule("06:00", "06:00", None)}
        self.assertFalse(_phl_schedule_is_open(hours, "k"))

    def test_closed_outside_window(self):
        hours = {"k": PhlSchedule("23:58", "23:59", frozenset({_js_weekday_today()}))}
        now = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M")
        if not ("23:58" < now < "23:59"):
            self.assertFalse(_phl_schedule_is_open(hours, "k"))


if __name__ == "__main__":
    unittest.main()
