"""What the commands print, and how."""



def test_a_verdict_is_coloured_and_other_lines_are_left_alone():
  from steadyhand._colour import GREEN, RED, paint

  assert GREEN in paint("steadyhand check: PASS  PCR plate setup")
  assert GREEN in paint("steadyhand plan: OK  PCR plate setup")
  assert RED in paint("steadyhand rehearsal: FAIL")
  assert RED in paint("  collisions: 8")
  assert paint("  collisions: 0") == "  collisions: 0"
  assert paint("  buffer: uses 8800 uL of 20000 uL supplied") == "  buffer: uses 8800 uL of 20000 uL supplied"


def test_colour_is_only_for_a_terminal_that_wants_it(monkeypatch):
  import io

  from steadyhand._colour import wanted

  monkeypatch.delenv("FORCE_COLOR", raising=False)
  monkeypatch.delenv("NO_COLOR", raising=False)
  assert not wanted(io.StringIO())
  monkeypatch.setenv("FORCE_COLOR", "1")
  assert wanted(io.StringIO())
  monkeypatch.setenv("NO_COLOR", "1")
  assert not wanted(io.StringIO())
