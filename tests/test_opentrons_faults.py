"""The seeded-fault suite on the Opentrons robots. The table is what steadyhand stops there today.

When a new check closes a gap, the outcome changes and this test fails: update the table here and
regenerate the tables with `steadyhand faults --robot opentrons-flex -o docs/faults-opentrons-flex.md`
and the same for `opentrons-ot2`.
"""

import pytest

from steadyhand import opentrons_robots as ot

pytestmark = pytest.mark.skipif(ot._definitions() is None, reason="Opentrons' software is not installed")

STOPPED_AT = {
  "source-runs-dry": "check",
  "well-overflows": "check",
  "well-not-on-the-plate": "read",
  "smaller-than-any-pipette-moves": "plan",
  "more-plates-than-slots": "plan",
  "too-shallow-to-reach": "rehearse",
  "one-tip-down-the-series": "-",
  "plate-and-reservoir-swapped": "rehearse",
  "plate-not-seated": "rehearse",
  "384-plate-loaded": "rehearse",
  "deep-well-plate-loaded": "-",
  "pcr-plate-loaded": "-",
  "tips-missing": "run",
  "longer-tips-loaded": "rehearse",
  "x-offset-onto-the-wall": "rehearse",
  "too-deep": "rehearse",
  "travel-too-low": "rehearse",
  "aspirate-above-the-liquid": "rehearse",
  "dispense-from-high-up": "rehearse",
}


@pytest.mark.parametrize("profile", [ot.FLEX, ot.OT2], ids=lambda p: p.name)
def test_every_fault_is_stopped_where_the_table_says(profile):
  from steadyhand.opentrons_faults import run_suite

  report = run_suite(profile)
  assert not report.clean.caught, report.clean
  assert {r.fault.name: r.outcome.stage for r in report.results} == STOPPED_AT
  missed = [name for name, stage in STOPPED_AT.items() if stage == "-"]
  assert [r.fault.name for r in report.missed] == missed
  assert f"16 of 19 planted mistakes stopped  ({profile.title})" in report.text()
  assert report.markdown().startswith(f"# What steadyhand stops, and what it does not: {profile.title}")
  assert report.markdown().count("**not stopped**") == 3


def test_cli_runs_the_suite_for_the_robot_named(capsys, tmp_path):
  from steadyhand.cli import main

  table = tmp_path / "faults.md"
  assert main(["faults", "--robot", "opentrons-ot2", "-o", str(table)]) == 0
  assert "16 of 19 planted mistakes stopped  (Opentrons OT-2)" in capsys.readouterr().out
  assert "| The plate sits 4.5 mm towards the back of its slot, half a well off. | deck | rehearse |" in table.read_text()
