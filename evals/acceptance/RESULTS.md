# Acceptance run, 13 Nov 2026

Twenty notes drawn from public kit manuals (see SOURCES.md), each drafted by a Claude Opus 5.5 agent
playing the model through `evals/step_intake.py`, then checked, planned and rehearsed with no hand
edits to what the model wrote. Run on drybench 0.6.0.

| note | draft | rounds | plan | rehearse | same draft on 0.8.0 |
|---|---|---|---|---|---|
| amplex_red_h2o2 | pass | 1 | pass | pass | pass |
| ampure_cleanup | pass | 1 | pass | pass | pass |
| bca_assay | pass | 1 | pass | pass | pass |
| bradford_assay | pass | 1 | pass | pass | pass |
| caspase_glo | pass | 1 | pass | crash | pass |
| celltiter_glo | pass | 1 | pass | crash | pass |
| dc_protein | pass | 1 | pass | pass | pass |
| griess_nitrite | pass | 1 | pass | pass | pass |
| kapa_library_quant | pass | 1 | pass | pass | pass |
| ldh_release | pass | 1 | pass | pass | pass |
| luna_qpcr_setup | pass | 1 | pass | pass | pass |
| micro_bca | pass | 1 | pass | pass | pass |
| mts_proliferation | pass | 1 | pass | pass | pass |
| mtt_assay | pass | 1 | pass | pass | pass |
| picogreen_dsdna | pass | 1 | pass | pass | pass |
| pierce_660 | pass | 1 | pass | pass | pass |
| prestoblue | pass | 1 | pass | pass | pass |
| q5_pcr_setup | pass | 1 | pass | pass | pass |
| restriction_digest | pass | 1 | pass | pass | pass |
| sandwich_elisa | pass | 1 | fail | - | pass |

**17 of 20 passed every stage at the first attempt.** The three that did not:

- `caspase_glo` and `celltiter_glo`: the model chose a plate PyLabRobot builds with its lid on, `plan`
  accepted it and `rehearse` crashed. Fixed in 0.7.0: the plan assumes lids are off and says so, and a
  command PyLabRobot refuses is a clean failure. The same two drafts now pass.
- `sandwich_elisa`: fifteen plate washes need about 2,200 tips and discard about 690 mL. The deck
  holds about 1,900 tips and the planner had one waste reservoir. Fixed in 0.8.0: the plan stops for
  tip reloads (two here) and adds waste reservoirs as they fill (four here). The same draft now
  passes, in about 40 seconds of rehearsal for 12,408 channel moves.

With those fixes all twenty drafts pass on 0.8.0, with no change to what the model wrote.

What a pass means: the file the model wrote runs through every check with no collision and no tip
clearly out of the liquid. It does not mean the file matches the note. Two were read against their
notes by hand (bca_assay, griess_nitrite) and matched; the rest were not. Ten of the seventeen carry
"possibly out of the liquid" findings in V-bottom plates and troughs, which do not fail a run.

Limits: one model family, agents driving the conversation by hand instead of a bare API call, notes
written by us from the manuals instead of the manuals themselves, and no robot. The intake guide was
edited after this run and has not been re-measured.
