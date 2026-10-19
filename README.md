# Pi Science Harness

A research-question-first extension for [Pi](https://pi.dev/). **Version 0.1.0 — experimental.**

The extension changes Pi's scientific operating instructions, tracks claims/evidence in a local ledger, provides relevance triage for tempting engineering detours, and offers an evidence-completeness check. It deliberately does **not** promise to establish scientific validity automatically.

## Install

Requires Pi with the current `@earendil-works/pi-coding-agent` extension API and Node 20+.

Extract the archive, then use the absolute directory path:

```sh
pi install /absolute/path/to/pi-science
```

Or run once for testing:

```sh
pi -e /absolute/path/to/pi-science/src/extension.ts
```

Pi supplies the `typebox` and `@earendil-works/pi-coding-agent` packages; they are declared as peers, not installed separately. **This archive was tested at the policy/core level but not against a running Pi session.**

## Use

```
/science question Does optimized agenda A beat agenda B on representative LCFRS grammars?
/science mode benchmarking
/science status
```

Ask Pi to design and run the experiment. The model can call:

- `science_record` — add hypotheses, claims, observations, issues, decisions.
- `science_triage` — classify proposed work as necessary/minimal/deferred.
- `science_sufficiency` — review evidence and clerical completeness.
- `science_update` — change claim status or resolve an issue with an explanation.

Use `/science report` to write `.pi/science/report.md` and `/science reset` to clear state. `/science question ...` starts a **new ledger and discards existing entries**. Export the report first if you need them.

Modes: `exploratory`, `confirmatory`, `benchmarking`, `replication`.

## Where the data goes

The extension writes `.pi/science/state.json` and reports to `.pi/science/report.md` under the current working directory. It is intentionally **project-scoped**, not Pi-session-scoped; it will not follow Pi `/tree` branching. Avoid concurrent Pi processes modifying the same ledger (writes are serialized only within one process). Add `.pi/science/` to `.gitignore` if your experiment metadata is private. State is local and no external telemetry is implemented.

## Constraints and future work

- Triage is advisory, not a forced gate on shell/tool execution. Pi still controls its normal operations and security protections.
- Sufficiency is *not* a validity proof; it checks for a question, recorded claims with non-open status, and absence of unresolved critical issues.
- Evidence references are provenance strings, not independently verified artifacts.
- Research ledger is file-backed; it is not integrated with session history or branch semantics.
- There is no LLM methodological-critic subagent in v0.1; call for a critical methodological review in the conversation.
- No production-ready experimental orchestration or cluster scheduler is added.

## Tests

```sh
node --test tests/*.test.js
```

## Project policy

The most important design choice is **validity-sensitive triage**. Scientific and execution blockers should be addressed; purely engineering work should be deferred unless the user asks for it. This policy never overrides safeguards, authorization, or scientifically material correctness checks.

## License

MIT.

## CGEL treebank analysis

An independent research deliverable (unrelated to the harness) that reads and
analyses the CGEL treebank (Reynolds, Ahmani & Schneider, EWT-CGEL):

* **Reader** — `cgel_reader.py`: a pure-stdlib parser for the `.cgel`
  S-expression trees (220 sentences in `cgel/`), verified round-trip +
  validation (2000+ node invariants, 0 mismatches).
* **Conventions** — `docs/cgel-conventions.md` and `cgel_grammar.py`: the
  discovered annotation conventions that couple function labels (edges) with
  constituent labels (categories) — the X-bar/projection skeleton and the
  head rule — with empirical tables and a mechanical checker
  (`cgel_conventions.py`).
* **Probability models** — `docs/cgel-models.md` and `cgel_models.py`: two
  models over analyses — Model A (labels independent) and Model B (support =
  convention-conforming analyses only, computed exactly by dynamic
  programming) — plus structural generative models that score tree shape as
  well as labels (`--structured`).
* **Bottom-up split-head models** — `docs/cgel-splithead.md` and
  `cgel_splithead.py`: an Eisner split-head generative model built up from
  words/POS (each head projects a category and takes stopped left/right
  argument sequences), which is properly normalised with no partition
  function or depth bound.
* **Coordination, markers and gaps** — `docs/cgel-coordination-gaps.md`
  (survey, decisions, results), `docs/cgel-coordgap-design.md` (the
  implementation), `cgel_coordgap_survey.py` and `cgel_coordgap.py`: a corpus survey of
  coordination shapes and gap/binder configurations, and a parser that adds
  to the head-driven core a coordination schema, a switchable treatment of
  marker tokens, and a gap feature carrying the category of the missing
  material (slash), passed across the board through coordination, so that
  each gap is co-indexed with the material
  that fills it (`fill_gaps`).  Gap positions are taken from the input.
  Evaluated by labelled attachment (LAS), collapsed brackets and gap
  filling, five-fold CV on all 220 sentences: LAS 0.54 at
  relative-frequency weights, 0.59 fitted; gaps filled with the gold
  material 31, fitted 41, of 119.  The chart is an active chart
  over structured labels (edge, label, derivation table) that builds each
  head's right side before its left, so every sentence parses; Viterbi
  ties are broken by a stated late-closure rule.  `cgel_coordgap_fit.py` is Model
  B over the chart: a conditional log-linear model normalised over the
  chart's own analyses (inside and outside passes, exact expectations)
  and fitted by conditional maximum likelihood.  `cgel_layering.py` is
  the CGELBank layering policy as a function, reproducing the gold
  projection chain for 96.8% of heads; `docs/cgel-correction-plan.md`
  records the corrections and what remains.
* **CYK parser** — `docs/cgel-headcyk.md` and `cgel_headcyk.py`: a
  head-driven (Eisner/Collins-style) parser that builds each constituent
  outward from its head using the split-head generative tables.  More than
  doubles the labelled F1 of the MLE-PCFG baseline (`cgel_cyk.py`) with no
  tuning; coverage is honestly partial (coordination/gaps).  A plain
  MLE-PCFG CYK (`cgel_cyk.py`) is kept as the disposable baseline.

```
python3 cgel_reader.py --validate cgel/*.cgel
python3 cgel_conventions.py --check cgel/*.cgel
python3 cgel_models.py --eval --structured --demo Here-sThePaper
python3 cgel_splithead.py
python3 cgel_headcyk.py --eval
python3 cgel_coordgap_survey.py
python3 cgel_coordgap.py --eval --ablate
python3 cgel_coordgap_fit.py --check && python3 cgel_coordgap_fit.py --fit
python3 tests/cgel_coordgap.test.py && python3 tests/cgel_coordgap_fit.test.py && python3 tests/cgel_headcyk.test.py && python3 tests/cgel_splithead.test.py && python3 tests/cgel_models.test.py && python3 tests/cgel_reader.test.py
```
