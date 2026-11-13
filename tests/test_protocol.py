"""The protocol file: strict reading, plain expansion, and liquid that has to add up."""

from pathlib import Path

import pytest

from drybench.cli import main
from drybench.protocol import WASTE, ProtocolError, Well, check, load, loads

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

HEAD = """
drybench: 0.1
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
  assert [str(p) for p in result.problems] == [
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
drybench: 0.1
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
  from drybench.protocol import check, loads

  text = """
drybench: 0.1
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
  from drybench.protocol import check, loads

  checked = check(loads("""
drybench: 0.1
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
