"""From a protocol file to commands, a rehearsal and a script that all agree."""

import asyncio
import inspect
import warnings
from pathlib import Path

import pylabrobot.resources as resources
import pytest
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.resources import Plate, set_tip_tracking, set_volume_tracking

from drybench import RecordingBackend
from drybench.cli import main
from drybench.planner import build_deck, emit, plan, plan_file, rehearse_plan, run
from drybench.protocol import check, loads

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
drybench: 0.1
name: test
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
  bulk: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: reservoir/A1, volume: 20 mL}
  sample: {in: plate/A1:H1, volume: 200 uL}
steps:
"""


def planned_from(text):
  checked = check(loads(text))
  assert checked.ok, checked.report()
  return plan(checked)


@pytest.fixture(scope="module")
def dilution():
  checked, planned = plan_file(EXAMPLES / "serial_dilution.yaml")
  return checked, planned, asyncio.run(rehearse_plan(planned))


def test_serial_dilution_plan(dilution):
  _, planned, _ = dilution
  assert planned.ok, planned.report()
  # 8 tips kept for the buffer, then 8 fresh ones for each of the 11 dilutions.
  assert planned.tips == {"hamilton_96_tiprack_300uL_filter": 96}
  assert max(len(c.channels) for c in planned.commands) == 8
  assert [p.carrier_type for p in planned.placements] == ["TIP_CAR_480_A00", "PLT_CAR_L5AC_A00"]
  assert "waste" in planned.labware


def test_serial_dilution_rehearses_cleanly(dilution):
  _, _, result = dilution
  assert result.ok, result.report()
  assert result.not_rehearsed == []


def test_pylabrobot_and_drybench_agree_on_every_volume(dilution):
  """Two independent ledgers: drybench's check, and PyLabRobot's trackers after the plan ran."""
  checked, _, result = dilution
  for well, volume in checked.volumes.items():
    assert result.volumes[f"{well.labware}_well_{well.well}"] == pytest.approx(volume, abs=1e-3)
  assert result.volumes["waste_well_A1"] == pytest.approx(checked.wasted)


def test_normalization_plan_and_rehearsal():
  checked, planned = plan_file(EXAMPLES / "normalization.yaml")
  assert planned.tips == {"hamilton_96_tiprack_50uL_filter": 16}
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok, result.report()
  for well, volume in checked.volumes.items():
    assert result.volumes[f"{well.labware}_well_{well.well}"] == pytest.approx(volume, abs=1e-3)


def test_emitted_script_does_exactly_what_was_rehearsed(dilution, tmp_path):
  _, planned, _ = dilution
  namespace: dict = {}
  exec(compile(emit(planned, source="serial_dilution.yaml"), "protocol.py", "exec"), namespace)

  set_volume_tracking(False)  # the script does not know what the wells start with
  set_tip_tracking(True)
  from_script = RecordingBackend(num_channels=8)
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    asyncio.run(namespace["main"](backend=from_script))

  async def direct():
    backend = RecordingBackend(num_channels=8)
    handler = LiquidHandler(backend=backend, deck=build_deck(planned))
    await handler.setup()
    await run(planned, handler)
    return backend

  set_volume_tracking(True)
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from_plan = asyncio.run(direct())

  assert len(from_script.steps) == len(from_plan.steps) > 1000
  for a, b in zip(from_script.steps, from_plan.steps):
    assert (a.kind, a.channel, a.resource, a.volume) == (b.kind, b.channel, b.resource, b.volume)
    assert a.reference == pytest.approx(b.reference)


def test_dependent_moves_are_not_put_in_one_command():
  planned = planned_from(HEAD + "  - serial_dilution: {start: plate/A1, steps: 3, direction: down, volume: 50 uL}\n")
  assert all(len(c.channels) == 1 for c in planned.commands if c.kind in ("aspirate", "dispense"))


def test_wells_closer_than_the_channel_pitch_are_not_put_in_one_command():
  dense = next(
    name
    for name in sorted(dir(resources))
    if inspect.isfunction(getattr(resources, name))
    and list(inspect.signature(getattr(resources, name)).parameters)[:1] == ["name"]
    and _rows(name) == 16
  )
  text = f"""
drybench: 0.1
name: dense
labware:
  plate: {{type: {dense}}}
liquids:
  sample: {{in: plate/A1:B1, volume: 20 uL}}
steps:
  - transfer: {{from: plate/A1:B1, to: plate/A2:B2, volume: 5 uL}}
"""
  planned = planned_from(text)
  assert all(len(c.channels) == 1 for c in planned.commands if c.kind in ("aspirate", "dispense"))


def _rows(name):
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      made = getattr(resources, name)(name="probe")
  except Exception:
    return None
  return made.num_items_y if isinstance(made, Plate) else None


def test_a_volume_bigger_than_the_largest_tip_is_split():
  planned = planned_from(HEAD + "  - transfer: {from: reservoir/A1, to: bulk/A1, volume: 2500 uL}\n")
  aspirated = [c.volumes[0] for c in planned.commands if c.kind == "aspirate"]
  assert len(aspirated) == 3
  assert all(v <= 1000 for v in aspirated)
  assert sum(aspirated) == pytest.approx(2500, abs=0.01)
  assert planned.tips == {"hamilton_96_tiprack_1000uL_filter": 1}


def test_smallest_tip_that_fits_is_chosen():
  planned = planned_from(HEAD + "  - transfer: {from: plate/A1, to: plate/A2, volume: 8 uL}\n")
  assert planned.tips == {"hamilton_96_tiprack_10uL_filter": 1}


def test_too_much_labware_for_one_deck_is_reported():
  plates = "\n".join(f"  p{i}: {{type: Cor_96_wellplate_360ul_Fb}}" for i in range(26))
  text = f"drybench: 0.1\nname: crowded\nlabware:\n{plates}\nliquids:\n  s: {{in: p0/A1, volume: 100 uL}}\nsteps:\n  - transfer: {{from: p0/A1, to: p1/A1, volume: 10 uL}}\n"
  planned = planned_from(text)
  assert any("a STARlet deck has 30" in str(p) for p in planned.problems)


def test_rehearse_and_emit_commands(tmp_path, capsys):
  out = tmp_path / "run"
  assert main(["rehearse", str(EXAMPLES / "normalization.yaml"), "--out", str(out), "--no-render"]) == 0
  assert (out / "protocol.py").exists() and (out / "scene.xml").exists()
  assert main(["emit", str(EXAMPLES / "normalization.yaml"), "-o", str(tmp_path / "script.py")]) == 0
  assert "await lh.aspirate" in (tmp_path / "script.py").read_text()
  assert main(["plan", str(EXAMPLES / "serial_dilution.yaml")]) == 0
  capsys.readouterr()


def test_rehearsal_stops_a_plan_that_pipettes_below_the_well_floor(dilution):
  _, planned, _ = dilution
  from dataclasses import replace

  too_deep = replace(planned, pipetting_height=-3.0)
  result = asyncio.run(rehearse_plan(too_deep))
  assert not result.ok
  assert {c.geom.split("/")[1] for c in result.collisions} == {"floor"}
