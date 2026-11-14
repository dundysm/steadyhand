"""The same protocol file planned for an Opentrons Flex and an OT-2, and timed waits on every robot."""

import json
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from steadyhand import opentrons_robots as ot
from steadyhand.cli import main
from steadyhand.planner import emit as hamilton_emit
from steadyhand.planner import plan as hamilton_plan
from steadyhand.protocol import ProtocolError, Well, check, loads
from steadyhand.robots import DEFAULT, ROBOTS, choose

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
steadyhand: 0.1
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
def test_dilution_on_a_flex_is_done_a_column_at_a_time():
  checked = checked_from(DILUTION)
  planned = ot.plan(checked, ot.FLEX)
  assert planned.ok, planned.report()
  assert planned.pipettes == {"left": "flex_8channel_50", "right": "flex_8channel_1000"}
  # Eight tips stand in for the one reused tip, and each column of the dilution takes eight fresh ones.
  assert planned.tips == {"opentrons_flex_96_filtertiprack_50ul": 8, "opentrons_flex_96_filtertiprack_200ul": 96}
  assert not planned.notes
  assert planned.slots == {"plate": "D1", "trough": "D2", "waste": "D3", "tips_50x8_1": "C1", "tips_200x8_1": "C2"}
  kinds = [a.kind for a in planned.actions]
  assert kinds.count("pick_up") == kinds.count("drop") == 13
  assert all(len(a.wells) == 8 for a in planned.actions if a.kind in ("pick_up", "aspirate", "dispense"))
  assert len(planned.actions) == 141  # a single channel needs 1,107
  # One pipette holds one set of tips: between a pick-up and its drop, only that mount works.
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


EIGHT = HEAD.replace("in: trough/A1, volume: 12 mL", "in: trough/A1:A2, volume: 12 mL") + """
  - transfer: {from: trough/A1, to: plate/A2:H12, volume: 30 uL}
  - transfer: {from: trough/A2, to: plate/C5, volume: 7 uL}
  - transfer: {from: plate/A2:D2, to: plate/A3:D3, volume: 10 uL}
  - transfer: {from: plate/A4:H4, to: plate/A5:H5, volume: 10 uL}
"""


@needs_opentrons
def test_the_plan_moves_the_same_liquid_as_the_check():
  for text in (DILUTION, EIGHT):
    for profile in (ot.FLEX, ot.OT2):
      checked = checked_from(text)
      planned = ot.plan(checked, profile)
      assert planned.ok, planned.report()
      held = {well: volume for wells, volume in checked.protocol.liquids.values() for well in wells}
      for action in planned.actions:
        if action.kind in ("aspirate", "dispense"):
          assert len(action.wells) in (1, 8) and action.wells[0] == action.well
          for name in action.wells:  # an 8-channel pipette moves the amount in every channel
            well = Well(action.labware, name)
            held[well] = held.get(well, 0.0) + (action.amount if action.kind == "dispense" else -action.amount)
            assert held[well] > -1e-6
      for well, volume in checked.volumes.items():
        assert abs(held[well] - volume) < 1e-3, (profile.name, well)
      assert abs(held.get(Well("waste", "A1"), 0.0) - checked.wasted) < 1e-3


@needs_opentrons
def test_a_whole_column_moves_with_eight_channels_and_everything_else_with_one():
  def reach(planned):
    return {
      step: {len(a.wells) for a in planned.actions if a.step == step and a.kind == "aspirate"} for step in range(4)
    }

  flex = planned_from(EIGHT)
  assert flex.pipettes == {"left": "flex_1channel_50", "right": "flex_8channel_50"}
  # A full plate from a reservoir and a column copied to the next: eight at once. One odd well and half a column: singly.
  assert reach(flex) == {0: {8}, 1: {1}, 2: {1}, 3: {8}}
  copied = [a for a in flex.actions if a.step == 3 and a.kind in ("aspirate", "dispense")]
  assert [(a.kind, a.well, a.wells[-1]) for a in copied] == [("aspirate", "A4", "H4"), ("dispense", "A5", "H5")]
  # The two pipettes take the same tips, but never from one rack: one takes them singly, the other by the column.
  assert [name for name in flex.labware if name.startswith("tips")] == ["tips_50_1", "tips_50x8_1"]
  assert flex.tips == {"opentrons_flex_96_filtertiprack_50ul": 5 + 12 * 8}
  picked = [(a.labware, a.wells) for a in flex.actions if a.kind == "pick_up"]
  assert picked[0] == ("tips_50x8_1", tuple(f"{row}1" for row in "ABCDEFGH"))
  assert ("tips_50_1", ("A1",)) in picked and ("tips_50_1", ("B1",)) in picked

  # An OT-2's 8-channel pipettes start at 1 and 20 uL: the 10 uL column falls between the pair chosen here.
  ot2 = planned_from(EIGHT, ot.OT2)
  assert ot2.pipettes == {"left": "p20_single_gen2", "right": "p300_multi_gen2"}
  assert reach(ot2) == {0: {8}, 1: {1}, 2: {1}, 3: {1}}

  # Unequal volumes down a column, and a plate with sixteen rows, are single-channel work.
  from steadyhand.protocol import load

  unequal = ot.plan(check(load(EXAMPLES / "normalization.yaml")), ot.FLEX)
  assert unequal.pipettes == {"left": "flex_1channel_50"}
  dense = planned_from(HEAD.replace("corning_96_wellplate_360ul_flat", "corning_384_wellplate_112ul_flat").replace(
    "volume: 200 uL", "volume: 50 uL") + """
  - transfer: {from: trough/A1, to: plate/A2:H2, volume: 20 uL}
""")
  assert dense.ok and {len(a.wells) for a in dense.actions if a.kind == "aspirate"} == {1}


def test_where_eight_channels_reach():
  def wells(labware, names):
    return [Well(labware, name) for name in names.split()]

  rows = {"plate": 8, "trough": 1, "dense": 16}
  assert ot._reach(wells("plate", "A3 B3 C3 D3 E3 F3 G3 H3"), rows) == "A3"
  assert ot._reach(wells("trough", "A2 A2 A2 A2 A2 A2 A2 A2"), rows) == "A2"
  assert ot._reach(wells("plate", "B3 A3 C3 D3 E3 F3 G3 H3"), rows) is None  # out of order
  assert ot._reach(wells("plate", "A3 B3 C3 D3 E3 F3 G3 H4"), rows) is None  # two columns
  assert ot._reach(wells("plate", "A1 A2 A3 A4 A5 A6 A7 A8"), rows) is None  # a row, not a column
  assert ot._reach(wells("trough", "A1 A1 A1 A1 A2 A2 A2 A2"), rows) is None  # two reservoir wells
  assert ot._reach(wells("dense", "A1 B1 C1 D1 E1 F1 G1 H1"), rows) is None  # tips are 9 mm apart, these wells 4.5
  assert ot._reach(wells("plate", "A3 B3 C3 D3 E3 F3 G3") + wells("trough", "A1"), rows) is None


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
  from steadyhand.protocol import load

  # Each sample tip moves a few microlitres and then mixes 25 uL. On an OT-2 the p20 cannot mix
  # 25 uL and the p300 cannot move less than 20, so the mix gets its own tip on the p300.
  from steadyhand.protocol import loads

  text = (EXAMPLES / "normalization.yaml").read_text(encoding="utf-8")
  assert "mix: {times: 3, volume: 15 uL}" in text  # the example itself mixes less, to stay under the liquid
  text = text.replace("mix: {times: 3, volume: 15 uL}", "mix: {times: 3, volume: 25 uL}")
  checked = check(loads(text, base=EXAMPLES))
  ot2 = ot.plan(checked, ot.OT2)
  assert ot2.ok, ot2.report()
  assert ot2.pipettes == {"left": "p20_single_gen2", "right": "p300_single_gen2"}
  assert sum(ot2.tips.values()) == checked.tips + 6 and "6 more tips than the check counted" in ot2.notes[0]
  mixes = [a for a in ot2.actions if a.kind == "aspirate" and a.amount == 25.0]
  assert mixes and {a.mount for a in mixes} == {"right"}
  # A Flex's 50 uL pipette does both, so nothing changes there.
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
  assert len(racks) == 9 and len(planned.slots) == 11 and planned.pipettes == {"left": "p20_multi_gen2"}
  reloads = [a for a in planned.actions if a.kind == "reload"]
  assert len(reloads) == 1 and reloads[0].racks == tuple(racks)
  picked = [(a.labware, tip) for a in planned.actions if a.kind == "pick_up" for tip in a.wells]
  assert len(set(picked[:864])) == 864 and picked[864] == ("tips_20x8_1", "A1") and len(set(picked[864:])) == 288
  script = ot.emit(planned)
  assert 'protocol.pause("Swap in full tip racks: tips_20x8_1 in slot 3,' in script
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
    assert script.count(".pick_up_tip(") == script.count(".drop_tip()") == 13


def simulator_here():
  try:
    from opentrons import simulate  # noqa: F401
  except Exception:  # not installed, or installed and unable to load on this Python
    return False
  return True


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_opentrons_own_simulator_runs_the_flex_protocol_and_stops_a_planted_mistake():
  planned = planned_from(DILUTION)
  script = ot.emit(planned)
  result = ot.simulate(script, ot.FLEX)
  assert result.ok, result.report()
  assert len(result.log) == len([a for a in planned.actions if a.kind != "reload"])
  assert result.log[0] == "Picking up tip from A1 of tips_200x8_1 on slot C2"
  assert result.report().startswith("Opentrons' simulator: PASS  (Opentrons Flex, opentrons ")

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
    assert result.ok and len(result.log) == 141, result.report()


# ---------------------------------------------------------------- choosing a robot


def test_the_robot_is_what_was_asked_for_then_what_the_file_says_then_the_hamilton():
  assert choose(None).name == DEFAULT == "hamilton-starlet"
  assert choose(None, "opentrons-flex").name == "opentrons-flex"
  assert choose("opentrons-ot2", "opentrons-flex").name == "opentrons-ot2"
  assert set(ROBOTS) == {"hamilton-starlet", "opentrons-flex", "opentrons-ot2"}
  with pytest.raises(KeyError):
    choose("tecan")
  with pytest.raises(ProtocolError) as refused:
    loads(WAITS.replace("name: waits", "name: waits\nrobot: tecan"))
  assert "no robot called 'tecan'" in str(refused.value)
  assert loads(WAITS.replace("name: waits", "name: waits\nrobot: opentrons-flex")).robot == "opentrons-flex"


def test_without_opentrons_software_a_file_with_twins_still_plans_and_emits_for_its_robots(monkeypatch):
  monkeypatch.setattr(ot, "_definitions", lambda: None)
  monkeypatch.setattr(ot, "_SHIPPED", {})
  # A PyLabRobot-named file needs nothing from Opentrons to be planned and written out.
  planned = ot.plan(checked_from(WAITS), ot.OT2)
  assert planned.ok and planned.labware["plate"] == "corning_96_wellplate_360ul_flat"
  assert "protocol.delay(seconds=1800)  # 30 min" in ot.emit(planned)
  # An Opentrons load name cannot be looked up, and the reader says what would let it.
  with pytest.raises(ProtocolError) as refused:
    loads(DILUTION)
  assert "pip install 'steadyhand[opentrons]'" in str(refused.value)


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_cli_plans_rehearses_and_emits_for_the_robot_named(tmp_path, capsys, monkeypatch):
  monkeypatch.delenv(ot.OT2_SIMULATOR, raising=False)
  path = tmp_path / "dilution.yaml"
  path.write_text(DILUTION.replace("name: test", "name: test\nrobot: opentrons-flex"))
  out = tmp_path / "out"
  assert main(["rehearse", str(path), "--out", str(out), "--no-render"]) == 0
  said = capsys.readouterr().out
  assert "(Opentrons Flex)" in said and "steadyhand rehearsal: PASS" in said and "Opentrons' simulator: PASS" in said
  assert "collisions: 0" in said and "tips out of the liquid or the well: 0" in said
  assert sorted(p.name for p in out.iterdir()) == [
    "protocol.py", "replay.html", "report.json", "report.txt", "run_log.txt", "scene.xml", "simulator.json"
  ]
  assert json.loads((out / "report.json").read_text())["ok"] is True
  assert json.loads((out / "simulator.json").read_text())["pass"] is True
  assert "steadyhand rehearsal: PASS" in (out / "report.txt").read_text() and "Opentrons' simulator: PASS" in (out / "report.txt").read_text()
  assert len((out / "run_log.txt").read_text().splitlines()) == 141

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
steadyhand: 0.1
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

  from steadyhand.planner import record_plan, run

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

  from steadyhand.planner import build_deck

  handler = Quiet()
  handler.deck = build_deck(planned)
  asyncio.run(run(planned, handler, on_wait=on_wait))
  assert waited == [1800.0, 300.0]


# ---------------------------------------------------------------- drafting for an Opentrons robot


def test_the_hamilton_prompt_is_the_one_the_intake_runs_were_measured_with():
  from steadyhand.intake import GUIDE, guide_for, labware_catalogue, messages_for

  plain = messages_for("text")
  assert plain == messages_for("text", None, "hamilton-starlet")
  assert plain[0]["content"] == GUIDE + "\nLABWARE\n" + labware_catalogue() + "\n"
  assert guide_for() is GUIDE and "robot:" not in GUIDE


@needs_opentrons
def test_a_draft_for_an_opentrons_robot_is_offered_opentrons_labware_and_examples_that_run():
  from steadyhand.intake import GUIDE, _problems_of, guide_for, labware_catalogue, messages_for

  for profile in (ot.FLEX, ot.OT2):
    guide = guide_for(profile.name)
    assert "Cor_96" not in guide and "troughplate" not in guide
    assert f"robot: {profile.name}   (required, exactly this)" in guide
    assert len(guide.splitlines()) == len(GUIDE.splitlines()) + 3  # one robot line in the sections and in each example
    offered = labware_catalogue(profile.name)
    assert messages_for("text", None, profile.name)[0]["content"] == guide + "\nLABWARE\n" + offered + "\n"
    first = guide.split("EXAMPLE 1")[1].split("\n", 1)[1].split("\nEXAMPLE 2")[0]
    second = guide.split("EXAMPLE 2")[1].split("\n", 1)[1]
    for text in (first, second):
      checked, problems = _problems_of(text, None, profile.name)
      assert not problems, problems
      assert checked.protocol.robot == profile.name
      assert all(f"{item.type}:" in offered for item in checked.protocol.labware.values())
      assert ot.plan(checked, profile).ok
      from steadyhand.intake import rehearsal_problems

      assert rehearsal_problems(checked, profile.name) == []  # what the guide shows the model has to rehearse

  lines = labware_catalogue("opentrons-flex").splitlines()
  assert len(lines) == len(ot.shipped_names()) >= 40
  assert "corning_96_wellplate_360ul_flat: 96 wells (8 rows x 12 columns), 360 uL each, flat bottom, last 34 uL out of reach" in lines
  assert any(line.startswith("nest_96_wellplate_2ml_deep: 96 wells (8 rows x 12 columns), 2000 uL each, V bottom, last ") for line in lines)
  # What cannot stand in a slot on its own is not offered, and not read.
  assert not any(word in line for line in lines for word in ("filter", "tips", "tiprack", "adapter", "tuberack"))
  assert ot.shipped_labware("millipore_96_wellplate_300ul_filter") is None


@pytest.mark.skipif(not simulator_here(), reason="Opentrons' simulator is not installed")
def test_every_plate_offered_for_a_flex_loads_in_opentrons_simulator():
  names = ot.shipped_names()
  for start in range(0, len(names), 10):
    lines = [
      "from opentrons import protocol_api",
      'requirements = {"robotType": "Flex", "apiLevel": "2.19"}',
      "def run(protocol):",
      '  protocol.load_trash_bin("A3")',
      '  tips = protocol.load_labware("opentrons_flex_96_filtertiprack_50ul", "A2")',
      '  pipette = protocol.load_instrument("flex_1channel_50", "left")',
      '  pipette.pick_up_tip(tips["A1"])',
    ]
    for name, slot in zip(names[start : start + 10], ot.FLEX.slots):
      lines.append(f'  well = protocol.load_labware("{name}", "{slot}").wells()[-1]')
      lines.append("  pipette.aspirate(1, well.bottom(1)); pipette.dispense(1, well.bottom(1))")
    result = ot.simulate("\n".join(lines) + "\n", ot.FLEX)
    assert result.ok, result.report()


@needs_opentrons
def test_a_draft_without_the_robot_line_is_sent_back():
  from steadyhand.intake import draft

  body = """labware:
  plate: {type: corning_96_wellplate_360ul_flat}
liquids:
  dye: {in: plate/A1, volume: 100 uL}
steps:
  - transfer: {from: plate/A1, to: plate/A2, volume: 50 uL}
"""
  replies = iter(["steadyhand: 0.1\nname: move\n" + body, "steadyhand: 0.1\nname: move\nrobot: opentrons-flex\n" + body])
  sent = []

  def model(messages):
    sent.append(messages[-1]["content"])
    return next(replies)

  result = draft("Move 50 uL from A1 to A2.", model, robot="opentrons-flex")
  assert result.ok and result.rounds == 2
  assert "the file must say `robot: opentrons-flex` after its name" in sent[1]
  assert result.checked.protocol.robot == "opentrons-flex"


# ---------------------------------------------------------------- a deck with no room to spare


def crowded(fillers, steps, plate="nest_96_wellplate_2ml_deep", volume="1.9 mL"):
  """A protocol with one deep-well plate, a trough and `fillers` more plates that only take up slots."""
  extra = "".join(f"\n  filler{n}: {{type: corning_96_wellplate_360ul_flat}}" for n in range(fillers))
  return f"""
steadyhand: 0.1
name: crowded
labware:
  plate: {{type: {plate}}}
  trough: {{type: nest_12_reservoir_15ml}}{extra}
liquids:
  sample: {{in: plate/A1:H12, volume: {volume}}}
  buffer: {{in: trough/A1:A2, volume: 12 mL}}
steps:
{steps}
"""


EMPTY_IT = "  - transfer: {from: plate/A1:H12, to: waste, volume: 1.9 mL}"


@needs_opentrons
def test_waste_reservoirs_give_way_before_tip_racks_and_are_emptied_in_a_pause():
  # 182 mL of waste is two reservoirs. With nine plates on the deck they fit, beside one rack of tips.
  roomy = planned_from(crowded(6, EMPTY_IT))
  assert roomy.ok and [name for name in roomy.labware if name.startswith("waste")] == ["waste", "waste_2"]
  assert len(roomy.slots) == 11 and "empty" not in [a.kind for a in roomy.actions]

  # One plate more and they do not. One reservoir stays and is emptied once; the tips are left alone.
  checked = checked_from(crowded(7, EMPTY_IT))
  tight = ot.plan(checked, ot.FLEX)
  assert tight.ok, tight.report()
  assert [name for name in tight.labware if name.startswith("waste")] == ["waste"] and len(tight.slots) == 11
  kinds = [a.kind for a in tight.actions]
  assert kinds.count("empty") == 1 and "reload" not in kinds
  assert "waste emptied: 1 times" in tight.report()
  at = kinds.index("empty")
  assert tight.actions[at].racks == ("waste",)

  def into_waste(actions):
    return sum(a.amount * len(a.wells) for a in actions if a.kind == "dispense" and a.labware == "waste")

  room = 0.9 * ot.WASTE_CAPACITY
  assert 0 < into_waste(tight.actions[at:]) <= room and room - 1900 * 8 < into_waste(tight.actions[:at]) <= room
  assert abs(into_waste(tight.actions) - checked.wasted) < 1e-3
  script = ot.emit(tight)
  assert f'protocol.pause("Empty the waste: waste in slot {tight.slots["waste"]}")' in script
  if simulator_here():
    assert ot.simulate(script, ot.FLEX).ok


@needs_opentrons
def test_on_a_tight_deck_each_pipette_keeps_to_one_size_of_tip():
  steps = """  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 100 uL}
  - transfer: {from: trough/A2, to: plate/A2:H2, volume: 800 uL}"""
  # Nine plates and reservoirs: the 8-channel pipette takes a 200 uL tip for one job and a 1000 uL tip for the other.
  roomy = planned_from(crowded(7, steps, volume="1 mL"))
  assert roomy.ok and not roomy.notes
  assert set(roomy.tips) == {"opentrons_flex_96_filtertiprack_200ul", "opentrons_flex_96_filtertiprack_1000ul"}
  # Ten: only one kind of rack fits, so it does both with the larger tip, and the plan says so.
  tight = planned_from(crowded(8, steps, volume="1 mL"))
  assert tight.ok, tight.report()
  assert tight.tips == {"opentrons_flex_96_filtertiprack_1000ul": 16} and len(tight.slots) == 11
  assert tight.notes == ["the deck is tight, so each pipette uses one size of tip"]
  # Eleven: there is no slot for tips at all.
  full = planned_from(crowded(9, steps, volume="1 mL"))
  assert not full.ok and "the Opentrons Flex has 11 for labware" in str(full.problems[0])


def test_waste_goes_round_a_limited_set_of_reservoirs():
  from steadyhand.planner import WASTE, _Unit, send_waste

  def units(count):
    return [_Unit(0, n, Well("plate", "A1"), WASTE, 40.0, None) for n in range(count)]

  # Each reservoir takes 90 of its 100: two moves of 40.
  work = units(7)
  names, problem, empties = send_waste(work, {}, 100.0)
  assert problem is None and empties == [] and names == ["waste", "waste_2", "waste_3", "waste_4"]
  assert [u.destination.labware for u in work] == ["waste", "waste", "waste_2", "waste_2", "waste_3", "waste_3", "waste_4"]
  work = units(7)
  names, _, empties = send_waste(work, {}, 100.0, limit=2)
  assert names == ["waste", "waste_2"] and empties == [4]  # both are full before the fifth move
  assert [u.destination.labware for u in work] == ["waste", "waste", "waste_2", "waste_2", "waste", "waste", "waste_2"]
  work = units(7)
  names, _, empties = send_waste(work, {}, 100.0, limit=1)
  assert names == ["waste"] and empties == [2, 4, 6] and {u.destination.labware for u in work} == {"waste"}
  assert send_waste(units(1), {"waste": "x"}, 100.0)[1] is not None


def test_a_pause_becomes_a_pause_in_the_opentrons_protocol():
  from test_protocol import PAUSED

  from steadyhand.opentrons_robots import FLEX, emit, plan
  from steadyhand.protocol import check, loads

  text = (PAUSED % "Spin the plate 1 min at 1000 g and put it back.").replace("name:", "robot: opentrons-flex\nname:", 1)
  text = text.replace("Cor_96_wellplate_360ul_Fb", "corning_96_wellplate_360ul_flat").replace("nest_12_troughplate_15000uL_Vb", "nest_12_reservoir_15ml")
  planned = plan(check(loads(text)), FLEX)
  assert planned.ok, [p.message for p in planned.problems]
  assert [a.kind for a in planned.actions if a.kind in ("wait", "pause")] == ["wait", "pause", "wait"]
  assert "pauses: 1" in planned.report()
  assert 'protocol.pause("Spin the plate 1 min at 1000 g and put it back.")' in emit(planned)


BEADS = """
steadyhand: 0.1
robot: %s
name: one bead wash
labware:
  beads: {type: %s}
  trough: {type: nest_12_reservoir_15ml}
liquids:
  wash: {in: trough/A1, volume: 10 mL}
  sample: {in: beads/A1:H1, volume: 100 uL}
steps:
  - magnet: {plate: beads, state: on}
  - wait: {duration: 2 min}
  - transfer: {from: beads/A1:H1, to: waste, volume: 90 uL}
  - magnet: {plate: beads, state: off}
  - transfer: {from: trough/A1, to: beads/A1:H1, volume: 200 uL, mix_after: {times: 5, volume: 150 uL}}
"""


def test_on_the_ot2_a_magnet_step_puts_the_plate_on_a_magnetic_module():
  from steadyhand.opentrons_robots import OT2, emit, plan
  from steadyhand.opentrons_scene import build_deck, tallest
  from steadyhand.protocol import check, loads

  planned = plan(check(loads(BEADS % ("opentrons-ot2", "nest_96_wellplate_2ml_deep"))), OT2)
  assert planned.ok, [p.message for p in planned.problems]
  assert planned.magnet == "beads" and planned.magnet_height == 6.8
  assert [a.amount for a in planned.actions if a.kind == "magnet"] == [1.0, 0.0]
  script = emit(planned)
  slot = planned.slots["beads"]
  assert f'magnet = protocol.load_module("magnetic module gen2", "{slot}")' in script
  assert 'deck["beads"] = magnet.load_labware("nest_96_wellplate_2ml_deep", label="beads")' in script
  assert script.index("magnet.engage(height_from_base=6.8)") < script.index("magnet.disengage()")
  compile(script, "emitted", "exec")
  deck = build_deck(planned)
  assert round(deck.get_resource("beads").get_absolute_location().z - deck.get_resource("trough").get_absolute_location().z, 2) == 82.25
  assert tallest(planned) > 82.25 + 40
  assert "Magnetic Module GEN2" in planned.report()


def test_a_magnet_step_is_refused_where_there_is_no_magnet_and_for_a_plate_with_no_magnet_height():
  from steadyhand.intake import for_a_person
  from steadyhand.opentrons_robots import FLEX, OT2, plan
  from steadyhand.planner import plan as hamilton_plan
  from steadyhand.protocol import check, loads

  flex = plan(check(loads(BEADS % ("opentrons-flex", "nest_96_wellplate_2ml_deep"))), FLEX)
  assert not flex.ok and "no magnet for the Opentrons Flex" in flex.problems[0].message and for_a_person(flex.problems[0])
  hamilton = hamilton_plan(check(loads(BEADS % ("hamilton-starlet", "nest_96_wellplate_2ml_deep"))))
  assert not hamilton.ok and any("no magnet for the Hamilton STARlet" in p.message for p in hamilton.problems)
  flat = plan(check(loads(BEADS % ("opentrons-ot2", "corning_96_wellplate_360ul_flat"))), OT2)
  assert not flat.ok and "gives no magnet height" in flat.problems[0].message
  assert not for_a_person(flat.problems[0])  # another plate settles this one


def test_the_magnet_goes_on_before_it_goes_off_and_stays_under_one_plate():
  from steadyhand.protocol import check, loads

  text = BEADS % ("opentrons-ot2", "nest_96_wellplate_2ml_deep")
  assert check(loads(text)).ok
  twice = check(loads(text.replace("state: off", "state: on")))
  assert [p.where for p in twice.problems] == ["steps[3].magnet"] and "already on" in twice.problems[0].message
  other = check(loads(text.replace("- magnet: {plate: beads, state: off}", "- magnet: {plate: trough, state: off}")))
  assert any("one magnet" in p.message for p in other.problems)
