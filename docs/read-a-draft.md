# Read a draft against its manual

steadyhand has a model draft a protocol file from a kit manual, then checks and rehearses it.
A draft that passes runs; whether it does what the manual asks is a separate question, and so
far only the project has answered it. If you have run one of these kits, fifteen minutes of
your reading tells the project something no simulation can.

## How

1. Pick a draft in [examples/drafts](../examples/drafts/README.md) for a kit, or a kind of
   assay, you know. Each is a model's draft exactly as it came, with no hand edits.
2. Open the maker's manual at the pages listed beside it.
3. Read the draft's `steps` against the protocol, then its `notes` and `chose`, which list
   what it left out and every decision the manual left open.
4. Answer the five questions below in a
   [draft review](https://github.com/dundysm/steadyhand/issues/new?template=draft_review.yml).

## The five questions

1. **Is it the manual's assay?** Every step there, in order, with the manual's volumes and times?
2. **Would you run it as written?** If not, what is the first thing you would change?
3. **Are the choices sensible?** The `chose` list says what the draft decided where the manual
   was silent: how many samples, where reagents stand, a dilution. Which would you have made
   differently?
4. **What would go wrong on the bench that the file does not show?** Bubbles, a reagent that
   foams or drips, a step that takes too long, a mix that is too gentle or too hard.
5. **What did it leave to a person, and is that the right split?** Pauses, what is prepared
   before the run, what happens off the deck.

You do not need to install anything or own a robot. If you want to see the run, `steadyhand
rehearse examples/drafts/calcium.yaml` writes a replay page.

Have a protocol of your own you want drafted? Open a
[protocol request](https://github.com/dundysm/steadyhand/issues/new?template=protocol_request.yml).
