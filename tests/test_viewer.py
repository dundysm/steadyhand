"""The HTML replay: one file, no network, built from the rehearsal alone."""

import asyncio
import json
from pathlib import Path

from drybench import rehearse
from drybench.cli import main
from drybench.demo import run_demo
from drybench.viewer import replay_data, replay_html

EXAMPLES = Path(__file__).parent.parent / "examples"


def demo(fault: str):
  deck, backend = asyncio.run(run_demo(fault))
  return rehearse(deck, backend.steps)


def test_replay_data_has_every_command_and_knows_where_the_wells_are():
  result = demo("none")
  data = replay_data(result, title="demo")
  assert data["ok"] and data["collisions"] == []
  assert [c["kind"] for c in data["commands"]] == ["pick_up_tip", "aspirate", "dispense", "drop_tip"]
  assert all(len(c["channels"]) == 8 for c in data["commands"])
  named = {channel[5] for command in data["commands"] for channel in command["channels"]}
  cavities = data["cavities"]
  assert named <= set(cavities) | {"trash"}, "everything the run touches is in the layout"
  well = next(cavities[name] for name in sorted(named) if name in cavities and cavities[name]["kind"] == "well")
  assert well["top"] > well["floor"] and well["box"][2] > well["box"][0]
  assert any(c["kind"] == "tip" for c in cavities.values())
  json.dumps(data)  # plain numbers and strings only


def test_a_collision_points_at_the_command_it_happened_in():
  result = demo("depth")
  data = replay_data(result)
  assert not data["ok"] and len(data["collisions"]) == 8
  assert {c["command"] for c in data["collisions"]} == {1}  # the aspirate, second command
  assert data["commands"][1]["kind"] == "aspirate"


def test_the_page_is_self_contained():
  page = replay_html(demo("offset"), title="a <b>title</b> & more")
  assert page.startswith("<!DOCTYPE html>") and "a &lt;b&gt;title&lt;/b&gt; &amp; more" in page
  for needs_network in ("http://", "https://", "src=", "@import"):
    assert needs_network not in page
  assert page.count("</script>") == 1, "nothing in the data may end the script block early"
  assert "__DATA__" not in page and "__TITLE__" not in page


def test_rehearse_writes_the_replay_next_to_the_report(tmp_path, capsys):
  assert main(["rehearse", str(EXAMPLES / "pcr_setup.yaml"), "--out", str(tmp_path), "--no-render"]) == 0
  page = (tmp_path / "replay.html").read_text(encoding="utf-8")
  assert "PCR plate setup" in page and "replay.html" in capsys.readouterr().out
