"""Rehearsing an Opentrons protocol that already exists, from Opentrons' own analysis of it."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from steadyhand import opentrons_import as oi
from steadyhand import opentrons_robots as ot
from steadyhand.protocol import check, load

pytestmark = pytest.mark.skipif(ot._definitions() is None, reason="Opentrons' software is not installed")

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def simulator_here() -> bool:
  """Whether Opentrons' own software loads here; on Python 3.10 one of its dependencies refuses."""
  try:
    from opentrons import simulate  # noqa: F401
  except Exception:
    return False
  return True


needs_analysis = pytest.mark.skipif(not simulator_here(), reason="Opentrons' analysis does not load here")
PLATE, TROUGH, TIPS, BIG = "corning_96_wellplate_360ul_flat", "nest_12_reservoir_15ml", "opentrons_96_tiprack_300ul", "corning_384_wellplate_112ul_flat"


def newest(load_name):
  folder = ot._definitions() / load_name
  return max(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())


def labware(identity, load_name, slot, shown=None):
  version = newest(load_name)
  return {
    "commandType": "loadLabware",
    "params": {"location": {"slotName": slot}, "loadName": load_name, "namespace": "opentrons", "version": version, "displayName": shown},
    "result": {"labwareId": identity, "definitionUri": f"opentrons/{load_name}/{version}"},
  }


def pipette(name="p300_single_gen2", mount="left", identity="pip"):
  return {"commandType": "loadPipette", "params": {"pipetteName": name, "mount": mount}, "result": {"pipetteId": identity}}


def at(kind, lab, well, volume=None, origin="bottom", z=1.0, tool="pip"):
  params = {"pipetteId": tool, "labwareId": lab, "wellName": well, "wellLocation": {"origin": origin, "offset": {"x": 0, "y": 0, "z": z}}}
  if volume is not None:
    params["volume"] = volume
  return {"commandType": kind, "params": params, "result": {}}


def here(kind, volume=None, tool="pip", **more):
  params = {"pipetteId": tool, **more}
  if volume is not None:
    params["volume"] = volume
  return {"commandType": kind, "params": params, "result": {}}


def liquid(lab, volumes):
  return {"commandType": "loadLiquid", "params": {"liquidId": "l", "labwareId": lab, "volumeByWell": volumes}, "result": {}}


def analysis(*commands, robot="OT-2 Standard"):
  deck = [labware("tips", TIPS, "4"), labware("plate", PLATE, "1", "assay plate"), labware("trough", TROUGH, "2", "reagents")]
  return {"robotType": robot, "metadata": {"protocolName": "by hand"}, "config": {"apiVersion": [2, 19]}, "errors": [], "commands": [*deck, pipette(), *commands]}


def rehearsed(doc):
  imported = oi.read(doc)
  return imported, asyncio.run(oi.rehearse_imported(imported))


def test_air_gaps_are_air_and_what_goes_in_the_trash_is_a_removal():
  imported, result = rehearsed(analysis(
    liquid("trough", {"A1": 5000.0}),
    at("pickUpTip", "tips", "A1", origin="top", z=0.0),
    at("aspirate", "trough", "A1", 100.0),
    at("aspirate", "trough", "A1", 20.0, origin="top", z=5.0),  # an air gap, as older API levels write it
    at("dispense", "plate", "A1", 120.0),                       # the air leaves first: 100 uL of liquid
    at("aspirate", "plate", "A1", 50.0),
    here("airGapInPlace", 10.0),
    here("moveToAddressableArea", addressableAreaName="fixedTrash"),
    here("dispenseInPlace", 60.0),
    here("blowOutInPlace"),
    here("dropTipInPlace"),
  ))  # fmt: skip
  moved = [(a.kind, a.labware, a.volume) for a in imported.acts if a.kind in ("aspirate", "dispense")]
  assert moved == [("aspirate", "reagents", 100.0), ("dispense", "assay_plate", 100.0), ("aspirate", "assay_plate", 50.0), ("dispense", "waste", 50.0)]
  assert imported.ok and result.ok, (imported.report(), result.report())
  assert any("air gaps: 1 draw" in note for note in imported.notes) and any("waste reservoir" in note for note in imported.notes)
  assert abs(result.volumes["assay_plate_well_A1"] - 50.0) < 1e-6 and abs(result.volumes["reagents_well_A1"] - 4900.0) < 1e-6
  assert not imported.assumed  # everything it drew from was declared or filled by the run


def test_a_well_asked_for_more_than_it_holds_one_filled_past_its_rim_and_a_volume_too_small_are_all_said():
  draws = [step for _ in range(4) for step in (at("aspirate", "trough", "A2", 100.0), at("dispense", "plate", "A1", 100.0))]
  imported, result = rehearsed(analysis(
    liquid("trough", {"A1": 150.0}),
    at("pickUpTip", "tips", "A1", origin="top", z=0.0),
    at("aspirate", "trough", "A1", 100.0), at("dispense", "plate", "B1", 100.0),
    at("aspirate", "trough", "A1", 100.0), at("dispense", "plate", "B2", 100.0),  # 50 uL is left
    *draws,                                                                       # 400 uL into a 360 uL well
    at("aspirate", "plate", "A1", 5.0), at("dispense", "plate", "C1", 5.0),       # under what a P300 moves
    here("dropTipInPlace"),
  ))  # fmt: skip
  text = "\n".join(imported.problems)
  assert len(imported.problems) == 3 and not imported.ok
  assert "draws 100 uL from reagents/A1, which holds 50.0 uL then" in text
  assert "fills assay_plate/A1 to 400.0 uL, and the well holds 360 uL" in text
  assert "draws 5 uL with the p300_single_gen2, 1 time; that pipette is specified for no less than 20 uL" in text
  # Nothing was declared for A2: it is given what the four draws take and what must stand under the tip.
  assert list(imported.assumed) == [("reagents", "A2")] and imported.assumed[("reagents", "A2")] > 400.0
  assert "wells drawn from with no liquid declared: 1" in imported.report()
  assert not result.ok and any(i.kind == "air" and i.resource == "reagents_well_A1" for i in result.liquid_failures)


def test_eight_channels_reach_a_column_one_trough_well_or_every_other_row_of_a_384_well_plate():
  body = lambda name: json.loads((ot._definitions() / name / f"{newest(name)}.json").read_text())  # noqa: E731
  assert oi._wells_reached(body(PLATE), "A3", 8) == tuple(f"{row}3" for row in "ABCDEFGH")
  assert oi._wells_reached(body(TROUGH), "A2", 8) == ("A2",) * 8
  assert oi._wells_reached(body(BIG), "B5", 8) == tuple(f"{row}5" for row in "BDFHJLNP")
  assert oi._wells_reached(body("corning_24_wellplate_3.4ml_flat"), "A1", 8) is None
  assert oi._wells_reached(body(PLATE), "C3", 1) == ("C3",)
  doc = analysis(at("pickUpTip", "tips", "A1", origin="top", z=0.0), at("aspirate", "trough", "A1", 50.0), at("dispense", "plate", "A2", 50.0), here("dropTipInPlace"))
  doc["commands"][3] = pipette("p300_multi_gen2")
  imported, result = rehearsed(doc)
  assert imported.pipettes == {"left": ("p300_multi_gen2", 8)} and imported.ok and result.ok, (imported.report(), result.report())
  assert len(result.steps) == 32  # four actions, eight channels each
  assert all(abs(result.volumes[f"assay_plate_well_{row}2"] - 50.0) < 1e-6 for row in "ABCDEFGH")


def test_what_the_replay_does_not_follow_stops_it_by_name_and_the_run_is_not_called_clean():
  move = {"commandType": "moveLabware", "params": {"labwareId": "plate", "newLocation": {"slotName": "3"}, "strategy": "manualMoveWithPause"}, "result": {}}
  imported, result = rehearsed(analysis(
    at("pickUpTip", "tips", "A1", origin="top", z=0.0), at("aspirate", "trough", "A1", 50.0), at("dispense", "plate", "A1", 50.0),
    move, at("aspirate", "plate", "A1", 50.0), at("dispense", "plate", "A2", 50.0), here("dropTipInPlace"),
  ))  # fmt: skip
  assert not imported.ok and "moveLabware, which the replay does not follow yet" in imported.stopped
  assert imported.followed == 7 and imported.commands == 11 and "followed 7 of 11 commands" in imported.report()
  assert [a.kind for a in imported.acts] == ["pick_up", "aspirate", "dispense"]  # what came before it is still rehearsed
  assert result.ok and len(result.steps) == 3

  ninety_six = analysis(at("pickUpTip", "tips", "A1", origin="top", z=0.0))
  ninety_six["commands"][3] = pipette("p1000_96")
  assert "96-channel" in oi.read(ninety_six).stopped


def test_modules_waits_and_labware_the_protocol_calls_waste_are_reported_for_what_they_are():
  doc = analysis(
    {"commandType": "loadModule", "params": {"model": "temperatureModuleV2", "location": {"slotName": "3"}}, "result": {"moduleId": "temp"}},
    {"commandType": "loadLabware", "params": {"location": {"moduleId": "temp"}, "loadName": PLATE, "namespace": "opentrons", "version": newest(PLATE), "displayName": "cold plate"}, "result": {"labwareId": "cold", "definitionUri": f"opentrons/{PLATE}/{newest(PLATE)}"}},
    labware("bin", "nest_1_reservoir_195ml", "5", "Liquid Waste"),
    {"commandType": "temperatureModule/setTargetTemperature", "params": {"moduleId": "temp", "celsius": 4}, "result": {}},
    {"commandType": "waitForDuration", "params": {"seconds": 60}, "result": {}},
    at("pickUpTip", "tips", "A1", origin="top", z=0.0),
    at("aspirate", "trough", "A1", 100.0), at("dispense", "cold", "A1", 100.0),
    at("aspirate", "cold", "A1", 100.0, z=0.5), at("dispense", "bin", "A1", 100.0, origin="top", z=0.0),
    here("dropTipInPlace"),
  )  # fmt: skip
  imported, result = rehearsed(doc)
  assert imported.labware["cold_plate"].on == "temperatureModuleV2" and imported.labware["cold_plate"].slot == "3"
  assert "waste_2" in imported.labware  # so a draw that ends there counts as a removal
  notes = "\n".join(imported.notes)
  assert "cold_plate on temperatureModuleV2" in notes and "1 temperatureModule commands" in notes and "1 waits and pauses" in notes
  assert imported.ok and result.ok, (imported.report(), result.report())


def test_a_saved_analysis_is_read_and_anything_else_is_refused(tmp_path):
  saved = tmp_path / "analysis.json"
  saved.write_text(json.dumps(analysis(at("pickUpTip", "tips", "A1", origin="top", z=0.0), here("dropTipInPlace"))))
  assert oi.load(saved).analysed_by == "a saved analysis"
  saved.write_text(json.dumps({"steps": []}))
  with pytest.raises(oi.ImportFailed, match="not an analysis"):
    oi.load(saved)


@needs_analysis
def test_steadyhands_own_flex_program_comes_back_through_opentrons_analysis_as_the_run_it_planned(tmp_path):
  from steadyhand import opentrons_scene

  checked = check(load(EXAMPLES / "bench_test.yaml"))
  planned = ot.plan(checked, ot.FLEX)
  own = asyncio.run(opentrons_scene.rehearse_plan(planned))
  script = tmp_path / "protocol.py"
  script.write_text(ot.emit(planned))
  imported = oi.load(script)
  result = asyncio.run(oi.rehearse_imported(imported))
  assert imported.ok and result.ok, (imported.report(), result.report())
  assert imported.profile is ot.FLEX and imported.analysed_by.startswith("opentrons ")
  assert len(result.steps) == len(own.steps) and not result.collisions
  assert len(imported.declared) == 2 and not imported.assumed
  for well, volume in checked.volumes.items():
    assert abs(result.volumes.get(f"{well.labware}_well_{well.well}", 0.0) - volume) < 1e-3, well


@needs_analysis
def test_the_example_with_three_mistakes_passes_opentrons_analysis_and_fails_here_for_all_three(tmp_path, capsys):
  from steadyhand.cli import main

  example = EXAMPLES / "opentrons" / "three_mistakes.py"
  doc, by = oi.analyse(example)
  assert doc["result"] == "ok" and not doc["errors"] and by.startswith("opentrons ")  # Opentrons has no objection
  assert main(["rehearse", str(example), "--out", str(tmp_path), "--no-render"]) == 1
  said = capsys.readouterr().out
  assert "problems: 3" in said and "steadyhand rehearsal: FAIL" in said
  for words in ("which holds 0.0 uL then", "to 400.0 uL, and the well holds 360 uL", "no less than 5 uL", "so it draws air"):
    assert words in said
  page = (Path(__file__).resolve().parent.parent / "docs" / "opentrons-import.md").read_text(encoding="utf-8")
  for line in said.splitlines():
    if line.startswith("    - ") and "possibly" not in line and "straight-walled" not in line:
      assert line.strip() in page, line  # the page shows what the command prints


@pytest.mark.skipif(not os.environ.get(ot.OT2_SIMULATOR), reason="no Opentrons release that takes OT-2 files is set up")
def test_a_hand_written_ot2_protocol_opentrons_accepts_has_its_three_mistakes_found(tmp_path, capsys):
  from steadyhand.cli import main

  script = tmp_path / "by_hand.py"
  script.write_text('''from opentrons import protocol_api

metadata = {"protocolName": "three mistakes", "apiLevel": "2.19"}


def run(protocol: protocol_api.ProtocolContext):
    tips = protocol.load_labware("opentrons_96_tiprack_300ul", 4)
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", 1, "assay plate")
    trough = protocol.load_labware("nest_12_reservoir_15ml", 2, "reagents")
    pipette = protocol.load_instrument("p300_single_gen2", "left", tip_racks=[tips])
    trough["A1"].load_liquid(protocol.define_liquid("buffer", "", "#4477aa"), 500)
    pipette.transfer(100, trough["A1"], [plate[w] for w in ("A1", "A2", "A3", "A4", "A5", "A6")], new_tip="once")
    pipette.pick_up_tip()
    for _ in range(4):
        pipette.aspirate(100, trough["A2"])
        pipette.dispense(100, plate["A1"])
    pipette.aspirate(5, plate["A1"])
    pipette.dispense(5, plate["B1"])
    pipette.drop_tip()
''')
  assert main(["rehearse", str(script), "--out", str(tmp_path / "out"), "--no-render"]) == 1
  said = capsys.readouterr().out
  assert "steadyhand import: FAIL  three mistakes  (Opentrons OT-2" in said and "Opentrons' analysis objects" not in said
  assert "problems: 3" in said and "which holds 0.0 uL then" in said and "to 400.0 uL" in said and "no less than 20 uL" in said
  report = json.loads((tmp_path / "out" / "report.json").read_text())
  assert report["import"]["assumed"] and not report["import"]["ok"]
