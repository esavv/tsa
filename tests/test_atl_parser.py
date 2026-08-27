#!/usr/bin/env python3
"""Tests for the ATL wait-times HTML parser."""

import os
import sys
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from scraper import _atl_parse_page, _atl_scan_items_to_rows

# Trimmed from a real www.atl.com/times/ response: two domestic checkpoints and
# one international, including the commented-out heading the live page carries.
SAMPLE = """
<html><body>
<div id='nesclasser2' class='container-fluid'>
  <div class='row'>
    <div class='col-lg-4 nesclasser2'>
      <div class='lomestic'><h1>DOMESTIC</h1></div>
      <div class='row'>
        <div class='col nomarginize'>
          <div class='lomestic'><h2>MAIN</h2><h3 style='color:#000;'>CHECKPOINT</h3></div>
        </div>
        <div class='col'>
          <div class='lomestic float-right'>
            <div class='declasser3'><button class="btn"><span style="color:#0aa700;">3</span></button></div>
          </div>
        </div>
      </div>
      <hr class='lomestic'>
      <div class='row'>
        <div class='col nomarginize'>
          <div class='lomestic'>
            <h2>SOUTH</h2>
            <!-- <h3 style="color:#c51700;">CHECKPOINT</h3> -->
            <h3 style='color:#35a;'>PRECHECK</h3>
          </div>
        </div>
        <div class='col'>
          <div class='lomestic float-right'>
            <div class='declasser3'><button class="btn"><span>12</span></button></div>
          </div>
        </div>
      </div>
    </div>
    <div class='col-lg-5 nesclasser1'>
      <div class='lomestic'><h1>INT'L</h1></div>
      <div class='row'>
        <div class='col nomarginize'>
          <div class='lomestic'><h2>MAIN</h2><h3>CHECKPOINT</h3></div>
        </div>
        <div class='col'>
          <div class='lomestic float-right'>
            <div class='declasser3'><button class="btn"><span>0</span></button></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""

# Trimmed from ATL's current redesign. Closed cards remain in the page but do
# not publish a numeric wait time.
REDESIGN_SAMPLE = """
<html><body>
<div class="atl-wt-gauge atl-security-wait-time atl-security-wait-time--live atl-wt-gauge--low"
     data-checkpoint="main" data-layout="card">
  <span class="atl-wt-sr-only">Main checkpoint: 10 minute wait, Low, open.</span>
  <div class="atl-wt-gauge__value">10 Min</div>
</div>
<div class="atl-wt-gauge atl-security-wait-time atl-security-wait-time--closed atl-wt-gauge--closed"
     data-checkpoint="north" data-layout="card">
  <div class="atl-wt-gauge__value atl-wt-gauge__value--state">Closed</div>
</div>
<div class="atl-wt-gauge atl-security-wait-time atl-security-wait-time--live atl-wt-gauge--low"
     data-checkpoint="intl_main" data-layout="card">
  <div class="atl-wt-gauge__value">3 Min</div>
</div>
</body></html>
"""

CHALLENGE_PAGE = (
    "<html><head><title>Just a moment...</title></head>"
    "<body>Performing security verification</body></html>"
)


class TestAtlParser(unittest.TestCase):
    def test_parses_open_redesign_cards_and_skips_closed_cards(self):
        rows = _atl_scan_items_to_rows(_atl_parse_page(REDESIGN_SAMPLE))
        self.assertEqual(
            [(row["terminal"], row["gate"], row["wait_minutes"]) for row in rows],
            [("Domestic", "Main", 10), ("International", "Main", 3)],
        )

    def test_parses_each_checkpoint_with_its_realm(self):
        items = _atl_parse_page(SAMPLE)
        self.assertEqual(
            [(i["realm"], i["checkpoint"], i["waitText"]) for i in items],
            [
                ("Domestic", "MAIN", "3"),
                ("Domestic", "SOUTH", "12"),
                ("International", "MAIN", "0"),
            ],
        )

    def test_ignores_commented_out_headings(self):
        items = _atl_parse_page(SAMPLE)
        south = next(i for i in items if i["checkpoint"] == "SOUTH")
        self.assertEqual(south["sub"], "PRECHECK")

    def test_rows_carry_queue_type_from_subheading(self):
        rows = _atl_scan_items_to_rows(_atl_parse_page(SAMPLE))
        by_gate = {(r["terminal"], r["gate"]): r for r in rows}
        self.assertEqual(by_gate[("Domestic", "SOUTH")]["queue_type"], "precheck")
        self.assertEqual(by_gate[("Domestic", "MAIN")]["queue_type"], "general")
        self.assertEqual(by_gate[("Domestic", "SOUTH")]["wait_minutes"], 12)
        self.assertEqual(by_gate[("International", "MAIN")]["wait_minutes"], 0)

    def test_challenge_page_yields_no_rows(self):
        self.assertEqual(_atl_parse_page(CHALLENGE_PAGE), [])


if __name__ == "__main__":
    unittest.main()
