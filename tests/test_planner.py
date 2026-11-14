"""From a protocol file to commands, a rehearsal and a script that all agree."""

import asyncio
import inspect
import warnings
from pathlib import Path

import pylabrobot.resources as resources
import pytest
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.resources import Plate, set_tip_tracking, set_volume_tracking

from steadyhand import RecordingBackend
from steadyhand.cli import main
from steadyhand.planner import build_deck, emit, plan, plan_file, rehearse_plan, run
from steadyhand.protocol import check, loads

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
steadyhand: 0.1
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
  # HEAD declares liquids that some of these short tests never touch; that one problem is not theirs.
  checked.problems[:] = [p for p in checked.problems if "no step draws from" not in p.message]
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


def test_pylabrobot_and_steadyhand_agree_on_every_volume(dilution):
  """Two independent ledgers: steadyhand's check, and PyLabRobot's trackers after the plan ran."""
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
steadyhand: 0.1
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
  text = f"steadyhand: 0.1\nname: crowded\nlabware:\n{plates}\nliquids:\n  s: {{in: p0/A1, volume: 100 uL}}\nsteps:\n  - transfer: {{from: p0/A1, to: p1/A1, volume: 10 uL}}\n"
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


def test_pcr_setup_example_rehearses_and_keeps_tips_on_idle_channels():
  checked, planned = plan_file(EXAMPLES / "pcr_setup.yaml")
  # 7 channels fit side by side in the reagent well, so 7 tips serve all the master mix.
  assert planned.tips == {"hamilton_96_tiprack_10uL_filter": 24, "hamilton_96_tiprack_50uL_filter": 7}
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok, result.report()
  for well, volume in checked.volumes.items():
    assert result.volumes[f"{well.labware}_well_{well.well}"] == pytest.approx(volume, abs=1e-3)


# ---------------------------------------------------------------- the editable plan file

EDITED = """
steadyhand_plan: "0.1"
pipetting_height: 2.5 mm
tips:
  - {type: hamilton_96_tiprack_1000uL, capacity: 1000 uL}
deck:
  - carrier: plates
    type: PLT_CAR_L5AC_A00
    rails: 3
    sites: [waste, null, reservoir, null, plate]
  - carrier: tips
    type: TIP_CAR_480_A00
    rails: 20
    sites: [null, null, tips_1000_1]
"""


def test_a_dumped_plan_file_read_back_gives_the_same_plan(dilution):
  from steadyhand.planner import dump_choices, loads_choices

  checked, planned, _ = dilution
  again = plan(checked, loads_choices(dump_choices(planned)))
  assert again.ok
  assert (again.commands, again.placements, again.tips) == (planned.commands, planned.placements, planned.tips)


def test_an_edited_plan_file_changes_tips_deck_and_height_and_still_rehearses(dilution):
  from steadyhand.planner import loads_choices

  checked, _, _ = dilution
  planned = plan(checked, loads_choices(EDITED))
  assert planned.ok, planned.report()
  assert planned.tips == {"hamilton_96_tiprack_1000uL": 96}
  assert [(p.carrier, p.rails) for p in planned.placements] == [("plates", 3), ("tips", 20)]
  assert planned.pipetting_height == 2.5
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok, result.report()
  for well, volume in checked.volumes.items():
    assert result.volumes[f"{well.labware}_well_{well.well}"] == pytest.approx(volume, abs=1e-3)
  assert "HEIGHT = 2.5" in emit(planned) and "rails=20" in emit(planned)


def test_a_plan_file_is_read_strictly_and_every_problem_is_listed():
  from steadyhand.planner import loads_choices
  from steadyhand.protocol import ProtocolError

  bad = """
steadyhand_plan: "0.1"
pipetting_height: 2
speed: fast
tips:
  - {type: hamilton_96_tiprack_300uL_filter, capacity: 500 uL}
  - {type: Cor_96_wellplate_360ul_Fb, capacity: 300 uL}
deck:
  - {carrier: b, type: TIP_CAR_480_A00, rails: 1.5, sites: [plate]}
"""
  with pytest.raises(ProtocolError) as caught:
    loads_choices(bad)
  where = {problem.where for problem in caught.value.problems}
  assert where == {"plan file.speed", "pipetting_height", "tips[0].capacity", "tips[1].type", "deck[0].rails"}
  with pytest.raises(ProtocolError, match="below the well floor"):
    loads_choices('steadyhand_plan: "0.1"\npipetting_height: -3 mm\n')


def test_a_deck_that_does_not_hold_the_plan_is_refused(dilution):
  from steadyhand.planner import loads_choices

  checked, _, _ = dilution
  deck = """
steadyhand_plan: "0.1"
deck:
  - {carrier: a, type: PLT_CAR_L5AC_A00, rails: 28, sites: [plate, tips_300_1, plate]}
  - {carrier: b, type: TIP_CAR_480_A00, rails: 30, sites: [ghost]}
"""
  planned = plan(checked, loads_choices(deck))
  assert not planned.ok
  said = "\n".join(str(problem) for problem in planned.problems)
  for expected in ("is a tip rack", "already on a", "does not fit", "no labware named 'ghost'", "overlaps a", "nothing places reservoir, waste"):
    assert expected in said, expected


def test_fewer_tip_sizes_split_big_transfers_and_refuse_big_mixes(dilution):
  from steadyhand.planner import Choices

  checked, _, _ = dilution
  small = plan(checked, Choices(tip_types=[(50.0, "hamilton_96_tiprack_50uL_filter")]))
  assert not small.ok and any("more than the largest tip holds" in str(p) for p in small.problems)


def test_cli_writes_a_plan_file_and_takes_it_back(tmp_path, capsys):
  chosen = tmp_path / "plan.yaml"
  assert main(["plan", str(EXAMPLES / "pcr_setup.yaml"), "-o", str(chosen)]) == 0
  chosen.write_text(chosen.read_text().replace("pipetting_height: 1 mm", "pipetting_height: 0.5 mm"))
  assert main(["emit", str(EXAMPLES / "pcr_setup.yaml"), "--plan", str(chosen), "-o", str(tmp_path / "s.py")]) == 0
  assert "HEIGHT = 0.5" in (tmp_path / "s.py").read_text()
  chosen.write_text("steadyhand_plan: \"0.1\"\nspeed: fast\n")
  assert main(["plan", str(EXAMPLES / "pcr_setup.yaml"), "--plan", str(chosen)]) == 1
  assert "cannot be read as a plan file" in capsys.readouterr().out


def test_a_plate_with_no_skirt_is_planned_in_an_adapter_and_says_so():
  from steadyhand.planner import needs_adapter
  from steadyhand.protocol import check, loads

  checked = check(loads("""
steadyhand: 0.1
name: unskirted pcr plate
labware:
  pcr:    {type: thermo_AB_96_wellplate_300ul_Vb_MicroAmp}
  source: {type: Cor_96_wellplate_2mL_Vb}
liquids:
  mix: {in: source/A1:H1, volume: 600 uL}
steps:
  - transfer: {from: source/A1:H1, to: pcr/A1:H1, volume: 20 uL}
  - mix: {wells: pcr/A1:H1, volume: 12 uL, times: 2}
"""))
  assert checked.ok
  planned = plan(checked)
  assert planned.ok, planned.report()
  assert needs_adapter("thermo_AB_96_wellplate_300ul_Vb_MicroAmp") and not needs_adapter("Cor_96_wellplate_2mL_Vb")
  assert planned.assumptions == [
    "pcr stands in a thermo_AB_96_plateadapter_MicroAmp (thermo_AB_96_wellplate_300ul_Vb_MicroAmp has no skirt)"
  ]
  with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    deck = build_deck(planned)
  plate = deck.get_resource("pcr")
  assert plate.parent.name == "pcr_adapter" and type(plate.parent).__name__ == "PlateAdapter"
  # the adapter lines the wells up with where a skirted plate's wells sit on the same site
  assert plate.get_item("A1").get_absolute_location("c", "c", "b").x == pytest.approx(253.3, abs=0.2)
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok, result.report()
  script = emit(planned)
  assert 'in_adapter(thermo_AB_96_wellplate_300ul_Vb_MicroAmp(name="pcr"))' in script
  assert "  thermo_AB_96_plateadapter_MicroAmp," in script


LIDDED = """
steadyhand: 0.1
name: reagent into a plate that ships with a lid
labware:
  plate:  {type: PerkinElmer_96_wellplate_400ul_Fb}
  trough: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  reagent: {in: trough/A1, volume: 20 mL}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H2, volume: 100 uL, tips: reuse}
"""


def test_a_plate_that_comes_with_a_lid_is_planned_with_the_lid_off_and_says_so():
  from steadyhand.protocol import check, loads

  planned = plan(check(loads(LIDDED)))
  assert planned.ok and planned.assumptions == ["the lid is off plate (PerkinElmer_96_wellplate_400ul_Fb comes with one)"]
  assert "assumes: the lid is off plate" in planned.report()
  assert asyncio.run(rehearse_plan(planned)).ok
  script = emit(planned)
  assert 'lid_off(PerkinElmer_96_wellplate_400ul_Fb(name="plate"))' in script
  namespace: dict = {}
  exec(compile(script, "emitted.py", "exec"), namespace)  # the emitted script builds its own deck and runs
  from pylabrobot.resources import set_volume_tracking

  set_volume_tracking(False)  # the script does not fill its own deck; PyLabRobot's default is off too
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      asyncio.run(namespace["main"]())
  finally:
    set_volume_tracking(True)


def test_a_command_pylabrobot_refuses_is_a_clean_failure(tmp_path, capsys):
  from steadyhand.planner import RunRefused, record_plan
  from steadyhand.protocol import check, loads

  planned = plan(check(loads(LIDDED)))

  def empty_the_rack(deck):
    for spot in deck.get_resource("tips_300_1").get_all_items():
      spot.tracker.remove_tip()

  with pytest.raises(RunRefused) as caught:
    asyncio.run(record_plan(planned, prepare=empty_the_rack))
  assert caught.value.number == 1 and "command 1 (pick_up at tips_300_1)" in str(caught.value)


def test_more_tips_than_the_deck_holds_are_planned_with_reloads_and_more_waste():
  from steadyhand.protocol import check, loads

  steps = "".join(
    f"  - transfer: {{from: {source}/A1, to: plate/A1:H12, volume: 300 uL}}\n"
    "  - transfer: {from: plate/A1:H12, to: waste, volume: 300 uL}\n"
    for source in ["trough", "trough_b"] * 6
  )
  text = """
steadyhand: 0.1
name: twelve washes of a whole plate
labware:
  plate:    {type: Cor_96_wellplate_360ul_Fb}
  trough:   {type: nest_1_troughplate_195000uL_Vb}
  trough_b: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  wash:   {in: trough/A1, volume: 190 mL}
  wash_b: {in: trough_b/A1, volume: 190 mL}
steps:
""" + steps
  checked = check(loads(text))
  assert checked.ok, checked.report()
  planned = plan(checked)
  assert planned.ok, planned.report()
  kinds = [c.kind for c in planned.commands]
  racks = [name for name in planned.labware if name.startswith("tips_")]
  assert sum(planned.tips.values()) == 2304 and len(racks) == 20  # 24 racks' worth of tips on 20 rack sites
  assert kinds.count("reload") == 1 and "tip reloads: 1" in planned.report()
  # 345.6 mL is discarded; one reservoir takes about 188 mL, so a second is added
  assert {"waste", "waste_2"} <= set(planned.labware) and "waste_3" not in planned.labware
  assert sum(len(p.sites) for p in planned.placements) <= 30 and max(p.rails for p in planned.placements) <= 25
  script = emit(planned)
  assert script.count('  reload(deck, "') == 1 and "def reload(deck, names):" in script
  result = asyncio.run(rehearse_plan(planned))
  assert result.ok, result.report()
  assert result.volumes["waste_well_A1"] + result.volumes["waste_2_well_A1"] == pytest.approx(345600)


def test_a_move_made_before_is_not_simulated_again(dilution):
  _, planned, _ = dilution
  once = asyncio.run(rehearse_plan(planned))
  seen = []
  again = asyncio.run(rehearse_plan(planned, on_sample=lambda *args: seen.append(1)))  # a callback turns reuse off
  assert once.ok and again.ok and once.path_length == pytest.approx(again.path_length)
  assert once.samples < again.samples == len(seen)


DEEP = """
steadyhand: 0.1
name: a small volume out of a deep well
labware:
  deep:  {type: %s}
  plate: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  stock: {in: deep/A1, volume: 500 uL}
steps:
  - transfer: {from: deep/A1, to: plate/A1:A3, volume: 5 uL}
"""


def _tips_for(definition):
  from steadyhand.planner import plan
  from steadyhand.protocol import check, loads

  planned = plan(check(loads(DEEP % definition)))
  assert planned.ok, [p.message for p in planned.problems]
  return planned


def test_a_tip_too_short_for_a_narrow_deep_well_is_swapped_for_one_that_reaches():
  # A 10 uL tip hangs 21.9 mm below the channel; these wells are 41 mm deep and 7 mm wide.
  planned = _tips_for("eppendorf_96_wellplate_1000ul_Vb")
  assert planned.tips == {"hamilton_96_tiprack_50uL_filter": 3}
  assert len(planned.longer_tips) == 1 and "3 tips are 50 uL where 10 uL would hold the volume" in planned.longer_tips[0]
  assert "longer tips:" in planned.report()


def test_a_shallow_plate_keeps_the_tip_the_volume_asks_for():
  planned = _tips_for("Cor_96_wellplate_360ul_Fb")
  assert planned.tips == {"hamilton_96_tiprack_10uL_filter": 3}
  assert not planned.longer_tips and "longer tips" not in planned.report()


def test_the_planner_and_the_replay_agree_on_how_wide_a_channel_is():
  from steadyhand.planner import CHANNEL_WIDTH
  from steadyhand.replay import BARREL_RADIUS

  assert CHANNEL_WIDTH == 2 * BARREL_RADIUS


def test_the_longer_tip_passes_the_rehearsal_the_short_one_failed(tmp_path):
  from steadyhand.cli import main

  path = tmp_path / "deep.yaml"
  path.write_text(DEEP % "eppendorf_96_wellplate_1000ul_Vb", encoding="utf-8")
  assert main(["rehearse", str(path)]) == 0


def test_a_pause_is_a_command_between_the_moves_it_separates_and_waits_around_it_stay_apart():
  from test_protocol import PAUSED

  from steadyhand.planner import emit, plan
  from steadyhand.protocol import check, loads

  planned = plan(check(loads(PAUSED % "Spin the plate 1 min at 1000 g and put it back.")))
  assert planned.ok
  stops = [(c.kind, c.volumes[0] if c.volumes else c.text) for c in planned.commands if c.kind in ("wait", "pause")]
  assert stops == [("wait", 300.0), ("pause", "Spin the plate 1 min at 1000 g and put it back."), ("wait", 180.0)]
  assert "pauses: 1 (the run stops for a person to do a step by hand)" in planned.report()
  script = emit(planned)
  assert 'pause(lh, "Spin the plate 1 min at 1000 g and put it back.")' in script
  compile(script, "emitted", "exec")


def test_the_parts_of_a_split_transfer_add_up_to_it_exactly():
  from steadyhand.planner import _share

  for volume, parts in ((50.0, 3), (100.0, 7), (1560.0, 2), (33.3, 3)):
    shares = [_share(volume, parts, part) for part in range(parts)]
    assert abs(sum(shares) - volume) < 1e-9, (volume, parts, shares)
