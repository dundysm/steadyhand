[steadyhand](../README.md) · [Commands](commands.md) · [Protocol file](protocol-format.md) · [Robots](robots.md) · [Drafting](drafting.md) · [PyLabRobot](pylabrobot.md) · [Opentrons protocols](opentrons-import.md) · [Limits](limits.md) · [Measurements](../evals/RESULTS.md)

# Draft a protocol from plain text

`draft` is the only place a language model is used. It writes the protocol file; steadyhand then
reads and checks that file exactly as if you had written it, plans it and rehearses it for the
robot, and sends whatever stops it back to the model, up to three times. A draft that passes
has been rehearsed. `--no-rehearse` stops at the check. The labware list the model is given
says, for every well whose inside shape is known, how much liquid a tip cannot reach, so it can
supply enough the first time.

```bash
# any command that reads a prompt on stdin and prints a reply
steadyhand draft notes.txt -o protocol.yaml --model-command "my-local-model"

# or an API, with the key in ANTHROPIC_API_KEY or OPENAI_API_KEY
steadyhand draft notes.txt -o protocol.yaml --provider anthropic --model MODEL_NAME
steadyhand draft notes.txt -o protocol.yaml --provider openai --model MODEL_NAME
```

`--provider openai` works with any OpenAI-compatible server; point `OPENAI_BASE_URL` at it.
When the text leaves something out, the model is told to choose the conventional option and
record the choice under `chose` in the file; what it left out goes under `notes`. `draft` prints
both. Manuals leave the same things open every time, so the guide fixes a default for each: 8
samples in column 1, the first complete protocol on the page, optional steps left out, the first
of two offered methods. Settle any of them yourself in your own words:

```bash
steadyhand draft manual.pdf --pages 4-5 -o protocol.yaml --model-command "my-local-model" \
  --decide "24 samples in columns 1 to 3; include the DNase step"
```

Read the file against your source before you use it.

To normalize samples to a common concentration, give it the readings as a CSV. The model is shown
the column names and the first few rows, so it can tell which column is which; the protocol it
writes names the file, and steadyhand reads the numbers from the file itself.

```bash
steadyhand draft notes.txt --samples readings.csv -o protocol.yaml --model-command "my-local-model"
```

The source can be a PDF, with `pip install steadyhand[pdf]`. Name the pages the protocol is on;
a whole manual is refused as too long.

```bash
steadyhand draft kit-manual.pdf --pages 4-6 -o protocol.yaml --model-command "my-local-model"
```

The text is taken as the PDF stores it, so tables come out as runs of words and a scanned page
has no text at all. It has been run on the protocol pages of 13 manufacturers' manuals: see
[what it does not do yet](limits.md) for how that went.

When the text asks for something that cannot work (more liquid than a named plate holds, a sample
too dilute to reach its target), the model is told to write it as stated and not to change your
numbers. `check` then refuses the file and says why, and the drafting stops there for you to decide.
