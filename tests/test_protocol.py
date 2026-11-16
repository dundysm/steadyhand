"""The protocol file: strict reading, plain expansion, and liquid that has to add up."""

from pathlib import Path

import pytest

from steadyhand.cli import main
from steadyhand.protocol import WASTE, ProtocolError, Well, check, load, loads

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
steadyhand: 0.1
name: test
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: reservoir/A1, volume: 20 mL}
  sample: {in: plate/A1:H1, volume: 200 uL}
steps:
"""


def problems_of(text):
  with pytest.raises(ProtocolError) as caught:
    loads(text)
  return [str(p) for p in caught.value.problems]


def test_serial_dilution_example_adds_up():
  result = check(load(EXAMPLES / "serial_dilution.yaml"))
  assert result.ok, result.report()
  transfers = [m for m in result.moves if m.kind == "transfer"]
  # 88 buffer fills, 8 series x 11 dilutions, 8 discards
  assert len(transfers) == 88 + 88 + 8
  assert result.tips == 1 + 88
  assert result.wasted == pytest.approx(800.0)
  # Every well of the plate ends at 100 uL.
  plate = {w: v for w, v in result.volumes.items() if w.labware == "plate"}
  assert len(plate) == 96
  assert all(v == pytest.approx(100.0) for v in plate.values())


def test_normalization_example_adds_up():
  result = check(load(EXAMPLES / "normalization.yaml"))
  assert result.ok, result.report()
  made = {w: v for w, v in result.volumes.items() if w.labware == "normalized"}
  assert len(made) == 8
  assert all(v == pytest.approx(50.0) for v in made.values())
  first = next(m for m in result.moves if m.source == Well("stock", "A1"))
  assert first.volume == pytest.approx(round(10 * 50 / 85.2, 2))
  # One tip for all the water, then a fresh one per sample.
  assert result.tips == 9


def test_every_problem_in_a_file_is_reported_at_once():
  found = problems_of(
    HEAD
    + """
  - transfer: {from: reservoir/A1, to: plate/A2:H2, volume: 100}
  - transfer: {from: tube/A1, to: plate/A3, volume: 10 uL, speed: fast}
  - mix: {wells: plate/A13, volume: 10 uL, times: 3}
"""
  )
  assert any("steps[0].transfer.volume" in p and "expected a volume" in p for p in found)
  assert any("steps[1].transfer.from" in p and "no labware called 'tube'" in p for p in found)
  assert any("steps[1].transfer.speed" in p and "unknown field" in p for p in found)
  assert any("steps[2].mix.wells" in p and "has no well A13" in p for p in found)


def test_unknown_labware_type_is_refused():
  found = problems_of(HEAD.replace("Cor_96_wellplate_360ul_Fb", "Imaginary_96_plate") + "  - wait: {duration: 5 min}\n")
  assert any("labware.plate.type" in p and "not a plate definition" in p for p in found)


def test_sources_and_destinations_must_pair_up():
  found = problems_of(HEAD + "  - transfer: {from: plate/A1:C1, to: plate/A2:B2, volume: 10 uL}\n")
  assert any("do not pair up" in p for p in found)


def test_taking_more_than_a_well_holds_is_caught():
  result = check(loads(HEAD + "  - transfer: {from: plate/A1, to: plate/A2, volume: 250 uL}\n"))
  assert [str(p) for p in result.problems if p.where.startswith("steps")] == [
    "steps[0]: takes 250 uL from plate/A1, which holds 200 uL at that point"
  ]


def test_overfilling_a_well_is_caught():
  result = check(loads(HEAD + "  - transfer: {from: reservoir/A1, to: plate/A1, volume: 200 uL}\n"))
  assert any("fills plate/A1 to 400 uL, over its 360 uL capacity" in str(p) for p in result.problems)


def test_volumes_below_the_limit_are_caught():
  result = check(loads(HEAD + "  - transfer: {from: plate/A1, to: plate/A2, volume: 0.5 uL}\n"))
  assert any("below the smallest volume allowed (1 uL)" in str(p) for p in result.problems)


def test_serial_dilution_that_runs_off_the_plate_is_caught():
  text = HEAD + "  - serial_dilution: {start: plate/A1, steps: 12, direction: right, volume: 50 uL}\n"
  result = check(loads(text))
  assert any("runs off the plate" in str(p) for p in result.problems)


def test_serial_dilution_discards_to_waste_by_default():
  text = HEAD + "  - serial_dilution: {start: plate/A1, steps: 2, direction: down, volume: 50 uL}\n"
  result = check(loads(text))
  assert [(str(m.source), str(m.destination)) for m in result.moves] == [
    ("plate/A1", "plate/B1"),
    ("plate/B1", "plate/C1"),
    ("plate/C1", str(WASTE)),
  ]


def normalization_with(rows, tmp_path):
  (tmp_path / "samples.csv").write_text("well,conc\n" + rows)
  (tmp_path / "protocol.yaml").write_text(
    """
steadyhand: 0.1
name: normalize
labware:
  stock: {type: Cor_96_wellplate_360ul_Fb}
  out: {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  water: {in: reservoir/A1, volume: 10 mL}
  dna: {in: stock/A1:B1, volume: 40 uL}
samples: {file: samples.csv, labware: stock, well: well, concentration: conc, unit: ng/uL}
steps:
  - normalize: {from: stock, to: out, diluent: reservoir/A1, target: 10 ng/uL, final_volume: 50 uL}
"""
  )
  return check(load(tmp_path / "protocol.yaml"))


def test_sample_too_dilute_to_normalize_is_caught(tmp_path):
  result = normalization_with("A1,85.2\nB1,8.0\n", tmp_path)
  assert any("stock/B1 is at 8 ng/uL, below the target of 10" in str(p) for p in result.problems)


def test_sample_too_concentrated_to_pipette_is_caught(tmp_path):
  result = normalization_with("A1,85.2\nB1,800\n", tmp_path)
  assert any("stock/B1 to out/B1: 0.62 uL is below the smallest volume" in str(p) for p in result.problems)


def test_check_command(capsys):
  assert main(["check", str(EXAMPLES / "serial_dilution.yaml")]) == 0
  assert "PASS" in capsys.readouterr().out
  assert main(["check", str(EXAMPLES / "does_not_exist.yaml")]) == 1
  capsys.readouterr()


def test_transfer_to_waste_discards_without_any_waste_labware():
  from steadyhand.protocol import check, loads

  text = """
steadyhand: 0.1
name: remove supernatant
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  sample: {in: plate/A1:H1, volume: 100 uL}
steps:
  - transfer: {from: plate/A1:H1, to: waste, volume: 80 uL}
"""
  checked = check(loads(text))
  assert checked.ok and checked.wasted == pytest.approx(640)
  assert all(volume == pytest.approx(20) for volume in checked.volumes.values())
  with pytest.raises(ProtocolError, match="cannot be mixed"):
    loads(text.replace("volume: 80 uL}", "volume: 80 uL, mix_after: {times: 2, volume: 10 uL}}"))


def test_a_problem_repeated_in_every_well_is_reported_once():
  from steadyhand.protocol import check, loads

  checked = check(loads("""
steadyhand: 0.1
name: overflow
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  trough: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  culture: {in: plate/A1:H12, volume: 200 uL}
  medium: {in: trough/A1, volume: 60 mL}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H12, volume: 250 uL}
"""))
  assert len(checked.problems) == 1
  said = str(checked.problems[0])
  assert "fills plate/A1 to 450 uL" in said and "the same in 95 more wells (B1, C1, ... H12)" in said


def test_a_liquid_no_step_touches_is_a_problem():
  from steadyhand.protocol import check, loads

  text = """
steadyhand: 0.1
name: wrong column
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  sample: {in: plate/A1:H1, volume: 200 uL}
  buffer: {in: plate/A2:H3, volume: 100 uL}
steps:
  - transfer: {from: plate/A2:H2, to: plate/A3:H3, volume: 50 uL}
"""
  problems = [str(p) for p in check(loads(text)).problems]
  assert len(problems) == 1 and problems[0].startswith("liquids.sample: no step draws from, adds to or mixes")
  assert check(loads(text.replace("from: plate/A2:H2", "from: plate/A1:H1"))).ok


def test_one_well_running_dry_again_and_again_is_one_line():
  from steadyhand.protocol import check, loads

  checked = check(loads("""
steadyhand: 0.1
name: dry
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  trough: {type: nest_1_troughplate_195000uL_Vb}
liquids:
  buffer: {in: trough/A1, volume: 250 uL}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 100 uL}
"""))
  assert len(checked.problems) == 1 and "and 5 more times after that" in str(checked.problems[0])


# ---------------------------------------------------------------- what a reused tip carries back

CARRY = """
steadyhand: 0.1
name: carry-over
labware:
  plate:     {type: Cor_96_wellplate_360ul_Fb}
  reservoir: {type: nest_12_troughplate_15000uL_Vb}
liquids:
  reagent: {in: reservoir/A1, volume: 5 mL}
  sample:  {in: plate/A1:H1, volume: 50 uL}
steps:
"""


def carried(steps, head=CARRY):
  return [str(p) for p in check(loads(head + steps)).problems if "reused tip" in str(p)]


def test_a_reused_tip_that_has_been_in_sample_may_not_go_back_into_the_reagent():
  found = carried("  - transfer: {from: reservoir/A1, to: plate/A1:H1, volume: 100 uL, tips: reuse}\n")
  assert found == [
    "steps[0]: a reused tip goes back into reservoir/A1 after it has been in plate/A1, which held sample; "
    "it carries that into reservoir/A1. Use tips: fresh for this step, or do it while those wells are still empty"
  ]


def test_what_is_not_carry_over_is_left_alone():
  # a fresh tip for every well
  assert carried("  - transfer: {from: reservoir/A1, to: plate/A1:H1, volume: 100 uL}\n") == []
  # one tip into wells that are still empty
  assert carried("  - transfer: {from: reservoir/A1, to: plate/A2:H2, volume: 100 uL, tips: reuse}\n") == []
  # one tip that tops up wells already holding the same liquid
  assert carried(
    "  - transfer: {from: reservoir/A1, to: plate/A2:H2, volume: 50 uL, tips: reuse}\n"
    "  - transfer: {from: reservoir/A1, to: plate/A2:H2, volume: 50 uL, tips: reuse}\n"
  ) == []
  # one tip into a single well of sample: it never goes back
  assert carried("  - transfer: {from: reservoir/A1, to: plate/A1, volume: 100 uL, tips: reuse}\n") == []
  # wells emptied to nothing first
  assert carried(
    "  - transfer: {from: plate/A1:H1, to: waste, volume: 50 uL}\n"
    "  - transfer: {from: reservoir/A1, to: plate/A1:H1, volume: 100 uL, tips: reuse}\n"
  ) == []
  # one tip down a dilution series: every well of the series ends up with both liquids
  assert carried(
    "  - transfer: {from: reservoir/A1, to: plate/A2:H4, volume: 50 uL, tips: reuse}\n"
    "  - serial_dilution: {start: plate/A1:H1, steps: 3, direction: right, volume: 25 uL, tips: reuse}\n"
  ) == []


def test_the_tip_of_a_transfer_that_mixes_and_is_thrown_away_is_not_carry_over():
  assert carried(
    "  - transfer: {from: reservoir/A1, to: plate/A1:H1, volume: 100 uL, mix_after: {times: 3, volume: 80 uL}}\n"
  ) == []


def test_a_labware_name_wrong_only_in_its_capital_letters_gets_the_right_one_named():
  from steadyhand.protocol import ProtocolError, loads

  text = """
steadyhand: 0.1
name: wrong case
labware:
  plate: {type: %s}
liquids:
  water: {in: plate/A1, volume: 100 uL}
steps:
  - transfer: {from: plate/A1, to: plate/A2, volume: 10 uL}
"""
  for wrong, right in (
    ("eppendorf_96_wellplate_250ul_Vb", "Eppendorf_96_wellplate_250ul_Vb"),
    ("cor_96_wellplate_360ul_fb", "Cor_96_wellplate_360ul_Fb"),
  ):
    try:
      loads(text % wrong)
    except ProtocolError as error:
      assert f"did you mean '{right}'?" in str(error), str(error)
    else:
      raise AssertionError("a wrong-case name was accepted")
  try:
    loads(text % "no_such_plate_at_all")
  except ProtocolError as error:
    assert "did you mean" not in str(error)


PAUSED = """
steadyhand: 0.1
name: a pause between two additions
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
  trough: {type: nest_12_troughplate_15000uL_Vb}
liquids:
  buffer: {in: trough/A1, volume: 5 mL}
steps:
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 100 uL}
  - wait: {duration: 5 min}
  - pause: %s
  - wait: {duration: 1 min}
  - wait: {duration: 2 min}
  - transfer: {from: trough/A1, to: plate/A1:H1, volume: 50 uL}
"""


def test_a_pause_is_read_counted_and_changes_no_volume():
  from steadyhand.protocol import check, loads

  checked = check(loads(PAUSED % "Spin the plate 1 min at 1000 g and put it back."))
  assert checked.ok and "pauses for a person: 1" in checked.report()
  assert "waiting: 8 min" in checked.report()
  assert [m.text for m in checked.moves if m.kind == "wait"] == ["", "Spin the plate 1 min at 1000 g and put it back.", "", ""]


def test_a_pause_needs_a_sentence_short_enough_to_show():
  from steadyhand.protocol import ProtocolError, loads

  for bad in ('""', "{duration: 5 min}", '"' + "x" * 201 + '"'):
    try:
      loads(PAUSED % bad)
    except ProtocolError as error:
      assert "steps[2].pause" in str(error)
    else:
      raise AssertionError(f"accepted pause: {bad}")


def test_a_file_that_names_what_it_cannot_do_without_is_refused_with_that_reason():
  from steadyhand.protocol import check, loads

  text = (PAUSED % "Spin the plate and put it back.").replace(
    "labware:", 'needs: ["A magnet under the plate while the supernatant is removed."]\nlabware:', 1
  )
  checked = check(loads(text))
  assert not checked.ok
  assert [p.where for p in checked.problems] == ["needs"]
  assert "needs a magnet under the plate while the supernatant is removed, which steadyhand cannot provide" in checked.problems[0].message
  assert check(loads(PAUSED % "Spin the plate and put it back.")).ok


EMPTIED = """
steadyhand: 0.1
name: take the medium off
labware:
  cells: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  medium: {in: cells/A1:H1, volume: 100 uL}
  control: {in: cells/A2, volume: 110 uL}
steps:
  - transfer: {from: cells/A1:H1, to: waste, volume: all, draw_from: surface}
  - transfer: {from: cells/A2, to: waste, volume: all}
"""


def test_volume_all_takes_whatever_each_well_holds_when_the_step_comes():
  checked = check(loads(EMPTIED))
  assert checked.ok, [p.message for p in checked.problems]
  assert [m.volume for m in checked.moves] == [100.0] * 8 + [110.0]
  assert not checked.volumes  # every well ends empty


def test_volume_all_is_only_for_liquid_sent_to_waste():
  with pytest.raises(ProtocolError) as refused:
    loads(EMPTIED.replace("from: cells/A2, to: waste", "from: cells/A2, to: cells/A3"))
  assert "`volume: all` is for liquid sent to waste" in str(refused.value)


def test_volume_all_of_an_empty_well_is_a_problem():
  twice = EMPTIED + "  - transfer: {from: cells/A2, to: waste, volume: all}\n"
  checked = check(loads(twice))
  assert [p.message for p in checked.problems] == ["takes all of cells/A2, which holds nothing at that point"]


LISTS = """
steadyhand: 0.1
name: Wells that are not one rectangle
labware:
  plate_1: {type: Cor_Cos_12_wellplate_6900ul_Fb}
  plate_2: {type: Cor_Cos_12_wellplate_6900ul_Fb}
  trough:  {type: nest_1_troughplate_195000uL_Vb}
liquids:
  medium: {in: [plate_1/A1:C2, plate_1/A3:B3, plate_2/A1], volume: 1 mL}
  pbs:    {in: trough/A1, volume: 30 mL}
steps:
  - transfer: {from: [plate_1/A1:C2, plate_1/A3:B3, plate_2/A1], to: waste, volume: all}
  - transfer: {from: trough/A1, to: [plate_1/A1:C2, plate_1/A3:B3, plate_2/A1], volume: 1 mL}
  - mix: {wells: [plate_2/A1, plate_1/A1], volume: 300 uL, times: 2}
"""


def test_wells_may_be_a_list_of_ranges_taken_in_the_order_written():
  protocol = loads(LISTS)
  sources = [str(well) for well in protocol.steps[0].source]
  assert sources == [f"plate_1/{w}" for w in ("A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3")] + ["plate_2/A1"]
  assert [str(well) for well in protocol.steps[2].wells] == ["plate_2/A1", "plate_1/A1"]
  checked = check(protocol)
  assert checked.ok, [p.message for p in checked.problems]
  assert [m.volume for m in checked.moves[:9]] == [1000.0] * 9
  assert checked.volumes[Well("plate_2", "A1")] == 1000.0


def test_a_list_of_wells_names_no_well_twice_and_says_which_item_is_wrong():
  assert problems_of(LISTS.replace("in: [plate_1/A1:C2, plate_1/A3:B3,", "in: [plate_1/A1:C2, plate_1/A2:B3,")) == [
    "liquids.medium.in: names plate_1/A2, plate_1/B2 more than once"
  ]
  assert problems_of(LISTS.replace("wells: [plate_2/A1, plate_1/A1]", "wells: [plate_2/A1, plate_1/D1]")) == [
    "steps[2].mix.wells[1]: plate_1 (Cor_Cos_12_wellplate_6900ul_Fb) has no well D1"
  ]
  assert "steps[2].mix.wells: expected at least one well or range in the list" in problems_of(
    LISTS.replace("wells: [plate_2/A1, plate_1/A1]", "wells: []")
  )


def test_a_serial_dilution_starts_from_one_range():
  text = (Path(__file__).parent.parent / "examples" / "serial_dilution.yaml").read_text()
  found = problems_of(text.replace("start: plate/A1:H1", "start: [plate/A1:D1, plate/E1:H1]"))
  assert found == ["steps[1].serial_dilution.start: a dilution series starts from one well or one range, not a list"]


def test_emptying_a_range_passes_over_the_wells_that_hold_nothing():
  text = EMPTIED.replace(
    "  - transfer: {from: cells/A2, to: waste, volume: all}\n",
    "  - transfer: {from: cells/A1:H2, to: waste, volume: all}\n",
  )
  assert text != EMPTIED
  checked = check(loads(text))  # column 1 was emptied by the step before; only A2 still holds liquid
  assert checked.ok, [p.message for p in checked.problems]
  assert checked.empty_wells == 15 and "wells passed over when emptying, because they held nothing: 15" in checked.report()
  assert [m.volume for m in checked.moves] == [100.0] * 8 + [110.0] and not checked.volumes
  last = text.replace("from: cells/A1:H2, to: waste", "from: [cells/A2, cells/A1:H1], to: waste")  # the empty wells come last
  assert check(loads(last)).ok and check(loads(last)).empty_wells == 8
