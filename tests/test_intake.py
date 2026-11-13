"""Intake: a model's draft is only accepted once it reads and checks like any other protocol."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from drybench.cli import main
from drybench.intake import (
  GUIDE,
  ModelError,
  anthropic_model,
  command_model,
  draft,
  extract_yaml,
  labware_catalogue,
  openai_model,
)

GOOD = """drybench: 0.1
name: Simple transfer
notes: ["Assumed a Corning 96-well plate; the text did not name one."]
labware:
  plate: {type: Cor_96_wellplate_360ul_Fb}
liquids:
  sample: {in: plate/A1, volume: 100 uL}
steps:
  - transfer: {from: plate/A1, to: plate/A2, volume: 50 uL}
"""
BAD = GOOD.replace("volume: 50 uL", "volume: 500 uL")  # takes more than the well holds


def scripted(*replies):
  """A stand-in model that gives its replies in order and remembers what it was sent."""
  calls = []

  def model(messages):
    calls.append([dict(m) for m in messages])
    return replies[len(calls) - 1]

  model.calls = calls
  return model


def test_a_good_draft_is_accepted_in_one_round():
  model = scripted(GOOD)
  result = draft("Move 50 uL from A1 to A2.", model)
  assert result.ok and result.rounds == 1
  assert result.checked.protocol.notes == ["Assumed a Corning 96-well plate; the text did not name one."]
  system, user = model.calls[0]
  assert system["role"] == "system" and "Cor_96_wellplate_360ul_Fb" in system["content"]
  assert "Move 50 uL from A1 to A2." in user["content"]


def test_yaml_is_pulled_out_of_a_chatty_reply():
  assert extract_yaml("Here you go:\n```yaml\n" + GOOD + "```\nHope that helps.") == GOOD
  assert extract_yaml("Sure.\n\n" + GOOD) == GOOD


def test_problems_are_sent_back_and_the_fix_is_accepted():
  model = scripted(BAD, GOOD)
  result = draft("Move 50 uL from A1 to A2.", model)
  assert result.ok and result.rounds == 2
  second_request = model.calls[1]
  assert second_request[-2] == {"role": "assistant", "content": BAD}
  assert "takes 500 uL from plate/A1, which holds 100 uL" in second_request[-1]["content"]


def test_a_draft_that_never_checks_out_is_refused():
  model = scripted(BAD, "not: [valid", BAD)
  result = draft("Move 50 uL from A1 to A2.", model, max_rounds=3)
  assert not result.ok and result.rounds == 3
  assert result.problems
  assert len(model.calls) == 3


def test_the_guide_names_only_fields_the_reader_accepts():
  """The example inside the guide must itself be a valid protocol."""
  example = GUIDE.split("EXAMPLE\n", 1)[1]
  assert draft("anything", scripted(example)).ok


def test_catalogue_lists_plates_with_shape_and_capacity():
  catalogue = labware_catalogue()
  assert "Cor_96_wellplate_360ul_Fb: 96 wells (8 rows x 12 columns), 360 uL each" in catalogue
  assert len(catalogue.splitlines()) > 40


def test_command_model_pipes_the_conversation_through_a_command(tmp_path):
  script = tmp_path / "model.py"
  script.write_text("import sys\nprompt = sys.stdin.read()\nprint('GOT', len(prompt), '[user]' in prompt)\n")
  reply = command_model(f"{sys.executable} {script}")([{"role": "user", "content": "hello"}])
  assert reply.startswith("GOT") and reply.strip().endswith("True")
  with pytest.raises(ModelError):
    command_model(f"{sys.executable} -c 'import sys; sys.exit(3)'")([{"role": "user", "content": "x"}])


@pytest.fixture
def stub_api():
  """A local server that records what it is sent and answers like each API does."""
  seen = []

  class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
      body = json.loads(self.rfile.read(int(self.headers["content-length"])))
      seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
      if self.path == "/v1/messages":
        reply = {"content": [{"type": "text", "text": GOOD}]}
      elif self.path == "/v1/chat/completions":
        reply = {"choices": [{"message": {"role": "assistant", "content": GOOD}}]}
      else:
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"no such path")
        return
      data = json.dumps(reply).encode()
      self.send_response(200)
      self.send_header("content-type", "application/json")
      self.send_header("content-length", str(len(data)))
      self.end_headers()
      self.wfile.write(data)

    def log_message(self, *args):
      pass

  server = HTTPServer(("127.0.0.1", 0), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  yield f"http://127.0.0.1:{server.server_port}", seen
  server.shutdown()


def test_anthropic_model_request_and_reply(stub_api):
  url, seen = stub_api
  model = anthropic_model("some-model", api_key="test-key", base_url=url)
  result = draft("Move 50 uL from A1 to A2.", model)
  assert result.ok
  sent = seen[0]
  assert sent["path"] == "/v1/messages"
  assert sent["headers"]["x-api-key"] == "test-key" and sent["headers"]["anthropic-version"] == "2023-06-01"
  assert sent["body"]["model"] == "some-model"
  assert "RULES" in sent["body"]["system"]
  assert [m["role"] for m in sent["body"]["messages"]] == ["user"]


def test_openai_compatible_model_request_and_reply(stub_api):
  url, seen = stub_api
  model = openai_model("some-model", api_key="test-key", base_url=url + "/v1")
  assert draft("Move 50 uL from A1 to A2.", model).ok
  sent = seen[0]
  assert sent["path"] == "/v1/chat/completions"
  assert sent["headers"]["authorization"] == "Bearer test-key"
  assert [m["role"] for m in sent["body"]["messages"]] == ["system", "user"]


def test_api_errors_are_reported_plainly(stub_api):
  url, _ = stub_api
  with pytest.raises(ModelError, match="answered 404"):
    openai_model("m", api_key="k", base_url=url + "/wrong")([{"role": "user", "content": "x"}])


def test_anthropic_model_needs_a_key(monkeypatch):
  monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
  with pytest.raises(ModelError, match="ANTHROPIC_API_KEY"):
    anthropic_model("some-model")


def test_draft_command(tmp_path, capsys):
  reply = tmp_path / "reply.yaml"
  reply.write_text(GOOD)
  notes = tmp_path / "notes.txt"
  notes.write_text("Move 50 uL from A1 to A2.")
  out = tmp_path / "protocol.yaml"
  code = main(
    ["draft", str(notes), "-o", str(out), "--model-command", f"{sys.executable} -c \"print(open(r'{reply}').read())\""]
  )
  printed = capsys.readouterr().out
  assert code == 0, printed
  assert out.read_text().strip() == GOOD.strip()
  assert "A model wrote this file" in printed
  assert main(["draft", str(notes), "-o", str(out)]) == 1
  capsys.readouterr()
