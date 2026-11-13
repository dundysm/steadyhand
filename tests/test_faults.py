"""The seeded-fault suite. The table below is what steadyhand stops today.

When a new check closes a gap, the suite's outcome changes and this test fails: update the
table here and regenerate docs/faults.md with `steadyhand faults -o docs/faults.md`.
"""

import pytest

from steadyhand.cli import main
from steadyhand.faults import FAULTS, run_suite

STOPPED_AT = {
  "source-runs-dry": "check",
  "well-overflows": "check",
  "volume-too-small": "check",
  "mix-more-than-the-well-holds": "check",
  "well-not-on-the-plate": "read",
  "amount-without-a-unit": "read",
  "labware-named-waste": "plan",
  "no-diluent": "check",
  "dilution-starts-in-the-wrong-column": "check",
  "source-drawn-below-the-tip": "rehearse",
  "one-tip-down-the-series": "-",
  "carrier-one-rail-off": "rehearse",
  "plate-and-reservoir-swapped": "rehearse",
  "384-plate-loaded": "rehearse",
  "deep-well-plate-loaded": "-",
  "lid-left-on": "run",
  "tips-missing": "run",
  "longer-tips-loaded": "rehearse",
  "shorter-tips-loaded": "rehearse",
  "x-offset-onto-the-wall": "rehearse",
  "too-deep": "rehearse",
  "travel-too-low": "rehearse",
  "aspirate-above-the-liquid": "rehearse",
  "dispense-from-high-up": "rehearse",
  "channels-too-close": "rehearse",
}


@pytest.fixture(scope="module")
def report():
  return run_suite()


def test_the_unchanged_protocol_runs_clean(report):
  assert not report.clean.caught, report.clean


def test_every_fault_is_stopped_where_the_table_says(report):
  assert [f.name for f in FAULTS] == list(STOPPED_AT)
  assert {r.fault.name: r.outcome.stage for r in report.results} == STOPPED_AT


def test_the_report_counts_and_names_what_got_through(report):
  missed = [name for name, stage in STOPPED_AT.items() if stage == "-"]
  assert [r.fault.name for r in report.missed] == missed
  assert f"{len(STOPPED_AT) - len(missed)} of {len(STOPPED_AT)} planted mistakes stopped" in report.text()
  assert report.markdown().count("**not stopped**") == len(missed)
