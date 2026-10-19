# Correction plan: reader–parser interface and X-bar in the parser

This is a plan, not a record of work done.  It follows a review that found
two kinds of fault in `cgel_coordgap.py`: the parser discards most of what
the reader provides, and it folds the treebank's projection levels into
one item per head and then guesses them back.  Both are symbolic errors;
nothing in this plan concerns probabilities.  Each step is small, has a
check that can be read in a minute, and can be reverted on its own.

## Part A: the reader–parser interface

**A1. One canonical token sequence.**  The reader offers three views of the
string (`tokens()` without gaps, `surface_events()` with gaps, and the
parser's own `sentence_tokens`).  Replace them, for everything downstream,
by one function on a `Sentence` that yields, in `# sent` order, one record
per surface position: the node, its word class, surface form, lemma,
`xpos`, attached punctuation, and whether it is a gap.  Extraction, the
parser input and the evaluation all read this and nothing else.
*Check*: joining the records reproduces `# sent` for all 220 sentences
(the reader's validator already does this for its own view).

**A2. Word classes refined from the annotation, at load time.**  The parser
takes the treebank's word classes as input; the treebank carries finer
distinctions that it does not spell out as classes.  Make them classes,
in one load-time function, documented as data interventions:

* verbs and auxiliaries by finiteness from `xpos`, which every one of the
  716 carries: finite (`VBZ`, `VBD`, `VBP`), non-finite (`VB`, `VBG`,
  `VBN`), modal (`MD`);
* complement-taking nouns and adjectives (`N_c`, `Adj_c`), already done;
* the eight complement-taking determinatives (`D_c`), optionally.

*Check*: the per-class argument table (which classes take `Subj`, `Obj`,
`Comp`, `Det`) shows finiteness separating subject-taking from
non-subject-taking verbs, and no class outside the intended ones taking
complements.

**A3. Carry lemma and punctuation.**  The parser input gains the lemma
(for any later lexicalised decision) and a punctuation flag per token
(for coordination and supplement boundaries).  Carried, not yet used.
*Check*: none needed beyond A1.

**A4. The three token-less leaves.**  Three annotator-supplied words
(`:correct` without `:t`) are neither tokens nor gaps.  Decide once: treat
their phrases as unfoldable (current behaviour, three sentences
affected) and say so in the data note.

## Part B: X-bar in the parser

**B0. The finding.**  A projection level in the treebank takes at most one
non-head dependent in about 95% of nodes, and its kind decides what it
takes: complements at the word level (`VP` over `V`: `Obj`, `Comp`,
`PredComp`; `PP` over `P`: `Obj`, `Comp`; `Nom` over `N_c`: `Comp`), one
adjunct per same-category re-projection (`VP` over `VP`, `Nom` over
`Nom`, `NP` over `NP`: `Mod`), the determiner at `NP` over `Nom`, the
subject at `Clause` over `VP`, the fronted element at `Clause` over
`Clause`.  Folding pooled all of these into one item and so lost the
levels' categories, their nesting order and their one-dependent limit;
the two-subjects, two-determiners and two-objects errors follow directly.

**B1. Chart items are level nodes.**  An item is (span, category, level
state); no folding, no re-expansion.  Three rules build them:

1. *word level*: a token of class `L` projects `X` and takes its
   complements, a stopped sequence on each side, from a table keyed by
   `L` (not by `X`), which is where valency lives and where the refined
   classes of A2 act;
2. *re-projection*: a complete `X` item becomes the head of a new `X`
   item that takes at most one dependent from the re-projection table of
   `X` (`Mod`, `Supplement`, `Prenucleus`, `Postnucleus`, a further
   `Comp` for the layered ditransitives);
3. *maximal projection*: a complete `Nom` becomes an `NP` taking at most
   one `Det` (or a `Supplement`); a complete `VP` becomes a `Clause` or
   `Clause_rel` taking at most one `Subj`.

Everything a rule may take, and which projections exist, is read off the
per-node tables that `cgel_splithead.iter_events` already produces (it
never folded); the level-kind table above is that inventory summarised.

**B2. No spurious ambiguity.**  A level's left and right dependents are
attached in a fixed order (right sequence, then left sequence), so each
tree has exactly one derivation; this matters for sums over the chart
(Model B), and is the per-level form of the head-outward discipline.

**B3. Coordination at any level.**  A conjunct is a level item, so `Nom`
and `Nom` coordinate under one determiner and `VP` and `VP` under one
subject; the 29 "coordination as head" cases that were off-support
return to the support.  The rule itself does not change.

**B4. Markers at their level.**  `(VP :Marker to :Head VP)` is a
re-projection of `VP` with a marker; `(Clause :Marker that :Subj … :Head
VP)` is the maximal projection with a marker.  MARK becomes a property of
the level rule rather than a separate rule guessing a level afterwards.

**B5. Gaps unchanged.**  The gap categories, discharge by binders and the
across-the-board rule ride on level items exactly as they rode on folded
items.

**B6. Support before weights.**  The first test of the new chart is
symbolic: with every rule weighted 1, is the gold tree an analysis of the
chart for the great majority of sentences, and which sentences fall out
and why.  Only then relative-frequency weights, then the Model B fit.

**B7. Evaluation.**  Brackets become meaningful at every level, so the
collapsed-bracket measure can be replaced by exact labelled brackets per
level alongside LAS; the gap-filling measure is unchanged.

## Order of work and the check at each step

| step | change | check |
|---|---|---|
| 1 | A1 canonical sequence | `# sent` round trip, 220/220 |
| 2 | A2 finiteness classes | per-class argument table |
| 3 | A3 lemma and punctuation carried | none |
| 4 | per-level inventory from the un-folded events | reproduces the level-kind table |
| 5 | B1–B4 level chart, all weights 1 | gold in support for ≥ 95% of sentences; list the rest |
| 6 | B5 gaps on level items | the four hand-built linking cases |
| 7 | relative-frequency weights | LAS on sentences ≤ 14 tokens, compared with the folded parser |
| 8 | Model B fit | held-out LAS and gap filling, as before |
| 9 | valency at the word level, keyed by refined class | repeated-argument count, expected zero by construction |

Steps 1–4 touch no parsing rule.  Step 5 is the one that replaces the
chart, and it is judged on support alone.
