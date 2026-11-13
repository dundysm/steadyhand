"""The same protocol file planned for an Opentrons Flex and an OT-2, and timed waits on every robot."""

import json
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from drybench import opentrons_robots as ot
from drybench.cli import main
from drybench.planner import emit as hamilton_emit
from drybench.planner import plan as hamilton_plan
from drybench.protocol import ProtocolError, Well, check, loads
from drybench.robots import DEFAULT, ROBOTS, choose

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
drybench: 0.1
name: test
labware:
  plate: {type: corning_96_wellplate_360ul_flat}
  trough: {type: nest_12_troughplate_15000uL_Vb}
liquids:
  buffer: {in: trough/A1, volume: 12 mL}
  stock: {in: plate/A1:H1, volume: 200 uL}
limits: {min_volume: 0.5 uL}
steps:
"""

DILUTION = HEAD + """
  - transfer: {from: trough/A1, to: plate/A2:H12, volume: 100 uL, tips: reuse}
  - serial_dilution: {start: plate/A1:H1, steps: 11, direction: right, volume: 100 uL, mix: {times: 3, volume: 80 uL}, discard: true}
  - wait: {duration: 10 min}
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 3 uL}
"""


def checked_from(text):
  checked = check(loads(text))
  checked.problems[:] = [p for p in checked.problems if "no step draws from" not in p.message]
  assert checked.ok, checked.report()
  return checked


def planned_from(text, profile=ot.FLEX):
  return ot.plan(checked_from(text), profile)


needs_opentrons = pytest.mark.skipif(ot._definitions() is None, reason="Opentrons' software is not installed")


# ---------------------------------------------------------------- labware


@needs_opentrons
def test_every_twin_is_the_same_plate_in_both_libraries():
  import pylabrobot.resources as resources

  for plr_name, (load_name, capacity) in ot.TWINS.items():
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      plate = getattr(resources, plr_name)(name="probe")
    folder = ot._definitions() / load_name
    body = json.loads(max(folder.glob("*.json"), key=lambda p: int(p.stem)).read_text())
    shipped = ot.shipped_labware(load_name)
    wells = plate.get_all_items()
    assert shipped["order"] == [w.get_identifier() for w in wells], plr_name
    assert (shipped["rows"], shipped["columns"]) == (plate.num_items_y, plate.num_items_x)
    assert shipped["capacity"] == capacity
    assert capacity <= wells[0].max_volume  # the check may only ever be the more generous of the two
    for well in wells:  # every well centre in the same place, and as deep
      theirs = body["wells"][well.get_identifier()]
      centre = well.get_absolute_location("c", "c", "b")
      assert abs(centre.x - theirs["x"]) < 0.1 and abs(centre.y - theirs["y"]) < 0.1, (plr_name, well.name)
      assert abs(well.get_size_z() - theirs["depth"]) < 0.1


@needs_opentrons
def test_a_protocol_file_may_name_labware_the_opentrons_way():
  protocol = loads(DILUTION)
  assert protocol.labware["plate"].library == "opentrons"
  assert protocol.labware["plate"].capacity == 360 and protocol.labware["plate"].order[:2] == ["A1", "B1"]
  assert protocol.labware["trough"].library == "pylabrobot"
  assert "corning_96_wellplate_360ul_flat" in ot.shipped_names()
  for not_a_plate in ("opentrons_96_filtertiprack_200ul", "opentrons_24_tuberack_nest_1.5ml_snapcap", "../2"):
    with pytest.raises(ProtocolError) as refused:
      loads(DILUTION.replace("corning_96_wellplate_360ul_flat", not_a_plate))
    assert "nor a plate or reservoir Opentrons ships" in str(refused.value)


@needs_opentrons
def test_a_plate_with_no_twin_is_refused_by_name_on_either_side():
  flex = planned_from(HEAD.replace("nest_12_troughplate_15000uL_Vb", "Cor_96_wellplate_2mL_Vb").replace("12 mL", "1 mL") + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 100 uL}
""")
  assert not flex.ok and "knows no Opentrons one" in flex.problems[0].message
  hamilton = hamilton_plan(checked_from(HEAD.replace("corning_96_wellplate_360ul_flat", "nest_96_wellplate_200ul_flat") + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 100 uL}
"""))
  assert not hamilton.ok and "knows no PyLabRobot one" in hamilton.problems[0].message


@needs_opentrons
def test_a_file_written_with_twins_plans_for_all_three_robots():
  checked = checked_from(DILUTION)
  assert hamilton_plan(checked).ok
  assert hamilton_plan(checked).labware["plate"] == "Cor_96_wellplate_360ul_Fb"
  assert ot.plan(checked_from(DILUTION), ot.FLEX).ok and ot.plan(checked_from(DILUTION), ot.OT2).ok


@needs_opentrons
def test_the_start_volume_is_held_to_what_opentrons_says_a_well_holds():
  # PyLabRobot gives this trough 15.7 mL a well, Opentrons 15 mL.
  text = DILUTION.replace("12 mL", "15.5 mL")
  assert hamilton_plan(checked_from(text)).ok
  flex = planned_from(text)
  assert not flex.ok and "15500 uL is more than a well of nest_12_reservoir_15ml holds (15000 uL)" in str(flex.problems[0])


# ---------------------------------------------------------------- pipettes, tips and order


@needs_opentrons
def test_dilution_on_a_flex_uses_two_pipettes_and_no_more_tips_than_the_check_counted():
  checked = checked_from(DILUTION)
  planned = ot.plan(checked, ot.FLEX)
  assert planned.ok, planned.report()
  assert planned.pipettes == {"left": "flex_1channel_50", "right": "flex_1channel_1000"}
  assert sum(planned.tips.values()) == checked.tips and not planned.notes
  assert planned.slots == {"plate": "D1", "trough": "D2", "waste": "D3", "tips_50_1": "C1", "tips_200_1": "C2"}
  kinds = [a.kind for a in planned.actions]
  assert kinds.count("pick_up") == kinds.count("drop") == checked.tips
  # One pipette holds one tip: between a pick-up and its drop, only that mount works.
  on: dict = {}
  for action in planned.actions:
    if action.kind == "pick_up":
      assert action.mount not in on
      on[action.mount] = True
    elif action.kind == "drop":
      del on[action.mount]
    elif action.kind in ("aspirate", "dispense"):
      assert action.mount in on
  assert not on
  # The wait sits between the dilution and the last transfer.
  at = kinds.index("wait")
  assert planned.actions[at].amount == 600
  assert {a.amount for a in planned.actions[at + 1 :] if a.kind == "aspirate"} == {3.0}
  assert all(a.amount != 3.0 for a in planned.actions[:at])


@needs_opentrons
def test_the_plan_moves_the_same_liquid_as_the_check():
  checked = checked_from(DILUTION)
  planned = ot.plan(checked, ot.OT2)
  held = {well: volume for wells, volume in checked.protocol.liquids.values() for well in wells for volume in [volume]}
  for action in planned.actions:
    well = Well(action.labware, action.well)
    if action.kind == "aspirate":
      held[well] = held.get(well, 0.0) - action.amount
      assert held[well] > -1e-6
    elif action.kind == "dispense":
      held[well] = held.get(well, 0.0) + action.amount
  for well, volume in checked.volumes.items():
    assert abs(held[well] - volume) < 1e-3, well
  assert abs(held[Well("waste", "A1")] - checked.wasted) < 1e-3


@needs_opentrons
def test_ot2_pipettes_are_chosen_by_volume_and_small_volumes_are_refused():
  both = planned_from(HEAD + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 5 uL}
  - transfer: {from: trough/A1, to: plate/A3, volume: 250 uL}
""", ot.OT2)
  # 250 uL is one draw for the p1000 and two for the p300 with its 200 uL filter tips.
  assert both.ok and both.pipettes == {"left": "p20_single_gen2", "right": "p1000_single_gen2"}
  assert [a.amount for a in both.actions if a.kind == "aspirate"] == [5.0, 250.0]

  split = planned_from(HEAD + """
  - transfer: {from: trough/A1, to: trough/A2, volume: 1500 uL}
""", ot.OT2)
  assert [a.amount for a in split.actions if a.kind == "aspirate"] == [750.0, 750.0]

  one = planned_from(HEAD + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 150 uL}
""", ot.OT2)
  assert one.pipettes == {"left": "p300_single_gen2"}

  small = planned_from(HEAD + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 0.5 uL}
""", ot.OT2)
  assert not small.ok and "0.5 uL is less than any pipette on the Opentrons OT-2 moves (1 uL)" in str(small.problems[0])

  three = planned_from(HEAD + """
  - mix: {wells: plate/A1, volume: 10 uL, times: 2}
  - mix: {wells: plate/B1, volume: 30 uL, times: 2}
  - mix: {wells: trough/A1, volume: 500 uL, times: 2}
""", ot.OT2)
  assert not three.ok and "need 3 pipettes" in str(three.problems[0]) and "holds two" in str(three.problems[0])
  assert planned_from(HEAD + """
  - mix: {wells: plate/A1, volume: 10 uL, times: 2}
  - mix: {wells: plate/B1, volume: 30 uL, times: 2}
  - mix: {wells: trough/A1, volume: 500 uL, times: 2}
""", ot.FLEX).ok


@needs_opentrons
def test_a_move_and_a_mix_no_one_pipette_can_both_do_get_a_tip_each():
  from drybench.protocol import load

  # Each sample tip moves a few microlitres and then mixes 25 uL. On an OT-2 the p20 cannot mix
  # 25 uL and the p300 cannot move less than 20, so the mix gets its own tip on the p300.
  checked = check(load(EXAMPLES / "normalization.yaml"))
  ot2 = ot.plan(checked, ot.OT2)
  assert ot2.ok, ot2.report()
  assert ot2.pipettes == {"left": "p20_single_gen2", "right": "p300_single_gen2"}
  assert sum(ot2.tips.values()) == checked.tips + 6 and "6 more tips than the check counted" in ot2.notes[0]
  mixes = [a for a in ot2.actions if a.kind == "aspirate" and a.amount == 25.0]
  assert mixes and {a.mount for a in mixes} == {"right"}
  # A Flex's 50 uL pipette does both, so nothing changes there.
  checked = check(load(EXAMPLES / "normalization.yaml"))
  flex = ot.plan(checked, ot.FLEX)
  assert flex.ok and not flex.notes and sum(flex.tips.values()) == checked.tips

  # What no pipette does at all is still refused, by step.
  big = planned_from(HEAD + """
  - mix: {wells: trough/A1, volume: 1500 uL, times: 2}
""")
  assert not big.ok and "mixing 1500 uL is more than the largest tip on the Opentrons Flex holds (1000 uL)" in str(big.problems[0])


def unit(tip, source, destination, volume=10.0, step=0, mix=None):
  return SimpleNamespace(
    tip=tip, source=Well(*source.split("/")), destination=Well(*destination.split("/")), volume=volume, step=step, mix=mix
  )


def test_work_is_put_together_tip_by_tip_only_when_no_well_can_tell():
  # Two dilution rows, interleaved the way eight channels would do them.
  rows = [unit(0, "p/A1", "p/A2"), unit(1, "p/B1", "p/B2"), unit(0, "p/A2", "p/A3"), unit(1, "p/B2", "p/B3")]
  assert [u.tip for u in ot._tip_by_tip(rows, {}, [])] == [0, 0, 1, 1]
  # Here tip 1 draws from a well that tip 0 comes back to fill: doing tip 0's work first would change it.
  crossed = [unit(0, "p/A1", "p/C1"), unit(1, "p/C1", "p/D1"), unit(0, "p/B1", "p/C1")]
  assert ot._tip_by_tip(crossed, {}, []) == crossed
  # Draws from one shared well may swap; so may fills of a waste reservoir.
  shared = [unit(0, "t/A1", "p/A1"), unit(1, "t/A1", "p/B1"), unit(0, "t/A1", "p/A2"), unit(1, "p/B1", "waste/A1"), unit(0, "p/A1", "waste/A1")]
  assert [u.tip for u in ot._tip_by_tip(shared, {}, ["waste"])] == [0, 0, 0, 1, 1]
  assert ot._tip_by_tip(shared, {}, []) == shared
  # Nothing moves across a wait or out of its step.
  waited = [unit(0, "p/A1", "p/A2"), unit(1, "p/B1", "p/B2"), unit(0, "p/A2", "p/A3")]
  assert ot._tip_by_tip(waited, {2: (60.0, 1)}, []) == waited
  stepped = [unit(0, "p/A1", "p/A2"), unit(1, "p/B1", "p/B2"), unit(0, "p/A2", "p/A3", step=1)]
  assert ot._tip_by_tip(stepped, {}, []) == stepped


@needs_opentrons
def test_more_tips_than_the_deck_holds_are_planned_with_pauses_to_reload():
  steps = "".join(f"\n  - transfer: {{from: trough/A{n}, to: plate/A1:H12, volume: 10 uL}}" for n in range(1, 13))
  text = HEAD.replace("in: trough/A1, volume: 12 mL", "in: trough/A1:A12, volume: 3 mL") + steps
  planned = planned_from(text, ot.OT2)
  assert planned.ok, planned.report()
  # 1,152 tips are 12 racks; two plates leave nine slots.
  assert planned.tips == {"opentrons_96_filtertiprack_20ul": 1152}
  racks = [name for name in planned.labware if name.startswith("tips_")]
  assert len(racks) == 9 and len(planned.slots) == 11
  reloads = [a for a in planned.actions if a.kind == "reload"]
  assert len(reloads) == 1 and reloads[0].racks == tuple(racks)
  picked = [(a.labware, a.well) for a in planned.actions if a.kind == "pick_up"]
  assert len(set(picked[:864])) == 864 and picked[864] == ("tips_20_1", "A1") and len(set(picked[864:])) == 288
  script = ot.emit(planned)
  assert 'protocol.pause("Swap in full tip racks: tips_20_1 in slot 3,' in script
  assert script.count('].reset()') == 9

  crowded = "".join(f"\n  p{n}: {{type: corning_96_wellplate_360ul_flat}}" for n in range(9))
  full = planned_from(HEAD.replace("\nliquids:", crowded + "\nliquids:") + """
  - transfer: {from: trough/A1, to: plate/A2, volume: 5 uL}
  - transfer: {from: trough/A1, to: plate/A3, volume: 150 uL}
""", ot.OT2)
  assert not full.ok and "need 13 slots; the Opentrons OT-2 has 11 for labware" in str(full.problems[0])


# ---------------------------------------------------------------- the protocol file and the simulator


@needs_opentrons
def test_the_emitted_protocol_is_python_that_says_which_robot_it_is_for():
  for profile, robot_type in ((ot.FLEX, "Flex"), (ot.OT2, "OT-2")):
    script = ot.emit(planned_from(DILUTION, profile), source="dilution.yaml")
    compile(script, "protocol.py", "exec")
    assert f'requirements = {{"robotType": "{robot_type}", "apiLevel": "2.19"}}' in script
    assert ('protocol.load_trash_bin("A3")' in script) == (profile is ot.FLEX)
    assert "protocol.delay(seconds=600)  # 10 min" in script
    assert 'deck["trough"][well].load_liquid(liquid, 12000.0)' in script
    assert script.count(".pick_up_tip(") == script.count(".drop_tip()") == 97


def simulator_here():
  try:
    import opentrons  # noqa: F401
  except ImportError:
    return False
  return True


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_opentrons_own_simulator_runs_the_flex_protocol_and_stops_a_planted_mistake():
  planned = planned_from(DILUTION)
  script = ot.emit(planned)
  result = ot.simulate(script, ot.FLEX)
  assert result.ok, result.report()
  assert len(result.log) == len([a for a in planned.actions if a.kind != "reload"])
  assert result.log[0] == "Picking up tip from A1 of tips_200_1 on slot C2"
  assert "PASS" in result.report() and "not checked on this robot: collisions" in result.report()

  first = 'right.aspirate(100.0, deck["trough"]["A1"].bottom(HEIGHT))'
  broken = ot.simulate(script.replace(first, first.replace("100.0", "400.0"), 1), ot.FLEX)
  assert broken.ran and not broken.ok
  assert "Cannot aspirate 400.0 µL when only 200 is available in the tip" in broken.error
  assert 'right.aspirate(400.0, deck["trough"]["A1"]' in broken.error  # the line it stopped at


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_an_ot2_protocol_is_simulated_only_where_a_simulator_still_takes_it(monkeypatch):
  script = ot.emit(planned_from(DILUTION, ot.OT2))
  monkeypatch.delenv(ot.OT2_SIMULATOR, raising=False)
  alone = ot.simulate(script, ot.OT2)
  if not alone.ran:  # the Opentrons release installed here has dropped the OT-2
    assert not alone.ok and "NOT RUN" in alone.report() and ot.OT2_SIMULATOR in alone.why_not
  older = os.environ.get(ot.OT2_SIMULATOR)
  if older:
    monkeypatch.setenv(ot.OT2_SIMULATOR, older)
    result = ot.simulate(script, ot.OT2)
    assert result.ok and len(result.log) == 1107, result.report()


# ---------------------------------------------------------------- choosing a robot


def test_the_robot_is_what_was_asked_for_then_what_the_file_says_then_the_hamilton():
  assert choose(None).name == DEFAULT == "hamilton-starlet"
  assert choose(None, "opentrons-flex").name == "opentrons-flex"
  assert choose("opentrons-ot2", "opentrons-flex").name == "opentrons-ot2"
  assert set(ROBOTS) == {"hamilton-starlet", "opentrons-flex", "opentrons-ot2"}
  with pytest.raises(KeyError):
    choose("tecan")
  with pytest.raises(ProtocolError) as refused:
    loads(DILUTION.replace("name: test", "name: test\nrobot: tecan"))
  assert "no robot called 'tecan'" in str(refused.value)
  assert loads(DILUTION.replace("name: test", "name: test\nrobot: opentrons-flex")).robot == "opentrons-flex"


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_cli_plans_rehearses_and_emits_for_the_robot_named(tmp_path, capsys, monkeypatch):
  monkeypatch.delenv(ot.OT2_SIMULATOR, raising=False)
  path = tmp_path / "dilution.yaml"
  path.write_text(DILUTION.replace("name: test", "name: test\nrobot: opentrons-flex"))
  out = tmp_path / "out"
  assert main(["rehearse", str(path), "--out", str(out)]) == 0
  said = capsys.readouterr().out
  assert "(Opentrons Flex)" in said and "drybench rehearsal: PASS" in said
  assert sorted(p.name for p in out.iterdir()) == ["protocol.py", "report.json", "report.txt", "run_log.txt"]
  assert json.loads((out / "report.json").read_text())["pass"] is True
  assert len((out / "run_log.txt").read_text().splitlines()) == 1107

  # --robot wins over the file; the Hamilton path is the one it always was.
  assert main(["plan", str(path), "--robot", "hamilton-starlet"]) == 0
  assert "TIP_CAR_480_A00" in capsys.readouterr().out
  assert main(["emit", str(path), "--robot", "opentrons-ot2", "-o", str(tmp_path / "ot2.py")]) == 0
  assert '"robotType": "OT-2"' in (tmp_path / "ot2.py").read_text()
  capsys.readouterr()

  # A plan file belongs to the Hamilton planner for now.
  assert main(["plan", str(path), "-o", str(tmp_path / "plan.yaml")]) == 1
  assert "cannot be edited yet" in capsys.readouterr().out
  assert main(["robots"]) == 0
  assert "opentrons-flex" in capsys.readouterr().out


# ---------------------------------------------------------------- waits on the Hamilton

WAITS = """
drybench: 0.1
name: waits
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  trough: {type: nest_12_troughplate_15000uL_Vb}
liquids:
  buffer: {in: trough/A1, volume: 5 mL}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 100 uL}
  - wait: {duration: 30 min}
  - mix: {wells: plate/A1:H1, volume: 50 uL, times: 2}
  - wait: {duration: 5 min}
"""


def test_a_timed_wait_is_in_the_hamilton_plan_and_its_script():
  planned = hamilton_plan(checked_from(WAITS))
  assert planned.ok
  kinds = [c.kind for c in planned.commands]
  assert kinds.count("wait") == 2 and kinds[-1] == "wait"
  first = kinds.index("wait")
  assert planned.commands[first].volumes == (1800.0,) and planned.commands[-1].volumes == (300.0,)
  # Everything before the first wait is the transfer; the mix comes after it.
  assert {c.resource for c in planned.commands[:first] if c.kind == "dispense"} == {"plate"}
  assert {c.resource for c in planned.commands[:first] if c.kind == "aspirate"} == {"trough"}
  assert {c.resource for c in planned.commands[first:] if c.kind == "aspirate"} == {"plate"}
  assert "waits: 2 (35 min in all)" in planned.report()
  script = hamilton_emit(planned)
  compile(script, "protocol.py", "exec")
  assert "await wait(lh, 1800)  # 30 min" in script and "await wait(lh, 300)  # 5 min" in script
  assert script.index("await wait(lh, 1800)") < script.index('"plate", "A1 B1 C1 D1 E1 F1 G1 H1"), vols=[50.0')


def test_a_run_waits_only_when_it_is_told_how():
  import asyncio

  from drybench.planner import record_plan, run

  planned = hamilton_plan(checked_from(WAITS))
  asyncio.run(record_plan(planned))  # a rehearsal: returns at once

  waited = []

  async def on_wait(seconds):
    waited.append(seconds)

  class Quiet:
    deck = None

    def __getattr__(self, name):
      async def nothing(*args, **kwargs):
        return None

      return nothing

  from drybench.planner import build_deck

  handler = Quiet()
  handler.deck = build_deck(planned)
  asyncio.run(run(planned, handler, on_wait=on_wait))
  assert waited == [1800.0, 300.0]
