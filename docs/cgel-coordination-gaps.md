# Coordination, markers and gaps: survey, design, implementation, results

The head-driven parser (`cgel_headcyk.py`) covers the part of the treebank
that X-bar describes well: a lexical head projecting a phrase and taking
dependents on each side.  It has no story for three things that are not head
projections: **coordination**, the **marker** tokens (subordinators and
coordinators), and the **gap/binder** links.  This note reports what the
corpus does in those areas (every count comes from
`python3 cgel_coordgap_survey.py`), states the design decisions one by one,
and reports what `cgel_coordgap.py` measures when they are implemented.
The implementation itself (representations, extraction, chart rules and
invariants, reconstruction, gap linking, evaluation) is documented in
`cgel-coordgap-design.md`.
The guiding choice is to keep the head-driven core untouched, add small
separate devices beside it, keep each decision visible and switchable where
it is genuinely debatable, and count the exceptions rather than build a
general machine.

A correction to `docs/cgel-headcyk.md`: it says the parser "requires every
token to be the head of a phrase" and blames the coverage gap on that.  That
requirement is an artefact of the earlier dynamic program, not a property of
head-driven grammar.  X-bar works for the projections; markers, coordination
and gaps need their own account.

## 1. What the earlier parser does

| situation | sentences | what happens |
|---|---:|---|
| no `Sdr` in the sentence | 130 | parses |
| contains an `Sdr` (*to*, *that*, *if*, …) | 90 | **no parse**: `Sdr` never projects, so the token has nowhere to go |
| contains a `Coordination` | 105 | parses only because the single `Marker-Head` *etc.* taught the model that `Coordinator` can project `NP`; the output is a flat run of NPs |
| contains a `GAP` | 72 | parses because gaps are deleted from the input; the gap site is simply absent |

On the extractor it is built on (`cgel_splithead.iter_events`): lexical
children are not entered in its span table, and a child without a span is
treated as ambiguous, so the node falls to "flat" mode.  The children this
affects are exactly the 236 `Marker` tokens, nothing else.  The effect is
that no table in the earlier model says anything about markers.  That is an
accident of bookkeeping; the question it leaves open, what a marker tells
the rest of the tree, is taken up in §4 as a decision in its own right.

## 2. Coordination: what the corpus does

131 `Coordination` nodes.

* **Shape.** 128 are a bare list of `Coordinate` children: 115 binary, 11
  ternary, 2 four-way.  The other three have a `Supplement` child (2) or are
  the *etc.* construction (`:Marker` + `:Head`, 1).
* **Marker placement.** The coordinator is *always the first child of its
  conjunct* and almost always of a non-initial conjunct (118 of 121).  The
  three initial-conjunct markers are correlatives (*both … and*, *whether …
  or*, one clause-initial *and*).  Coordinators never attach to the
  `Coordination` node itself.
* **Categories.** 122 coordinations have conjuncts of one category; 9 are
  unlike (`AdjP+NP`, `PP+AdjP`, `Clause+AdjP`, …), including the fused
  labels `NP+PP`, `NP+AdvP`, `NP+AdjP`, `NP+Clause`.  Nested coordination
  occurs twice.
* **Where it sits.** Root (34), object of a preposition (16), modifier in
  `Nom` (15), *head* of `Clause`/`VP`/`NP`/`DP` (29), object, complement or
  predicative of a verb (21), a scatter of others.  The node is transparent:
  it sits wherever its conjunct category could sit.

Subordinators are placed the same way one level down: `Sdr` is always the
first child of the clause or VP it marks (*to* before a `VP` head 75 times,
*that*/*if*/*whether*/*for* before a `Clause`/`Clause_rel` 47 times), and it
is never a head.

## 3. Decision A: coordination is a list

    COORD   Coordination(X)  ->  X  conjunct+        (like conjuncts only)

The first conjunct is a bare `X`; every further conjunct is an `X` beginning
with a coordinator, except that a middle conjunct may be bare (*develop,
build, flight-test, and operate*).  The result is category `Coordination`
and may fill any slot the split-head tables already let a `Coordination`
fill.  In the chart it is built from complete constituents; the head-driven
tables are not involved.  It is scored by the conjunct scores, a geometric
length term and a bare-conjunct term (§7 says what that amounts to).

The condition on the conjuncts is CGEL's (ch. 15 §3.1): they must be
alike in function, and "a difference of category is generally tolerated
where there is likeness of function".  The chart enforces exactly that:
every conjunct's category must be licensed in the slot the coordination
fills, and the conjuncts share their gap state but not their category.
(An earlier version required like categories, after CGELBank's practice
of reading a coordination's nature off its conjuncts' categories; the
author chose CGEL's condition, and the unlike-category cases, 9 of 131,
returned to the support.)

Not covered, deliberately: initial-marker correlatives (3), a
`Supplement` inside a `Coordination` (2), *etc.* (1), and **a
`Coordination` as the head of a larger phrase** (29 nodes: *the* [*crew and
cargo*], *'ll* [*call and …*]).  The last is the largest gap: the chart's
heads are tokens, and a coordination has none, so *the fire alarm and
strobe light* comes out as *the fire alarm* coordinated with *strobe light*.

## 4. Decision B: what a marker tells the rest of the tree

A marker token is not a word with a projection, but it is not noise either:
*that* tells the governing verb that its complement is a finite declarative,
*to* that it is non-finite, *and* that a conjunct follows, *whether* that an
interrogative follows.  Where that information goes is a modelling decision
and the corpus does not settle it, so the implementation keeps it as a
switch (`markers=`) and measures the alternatives:

| mode | what the marker does | who sees it |
|---|---|---|
| `schema` | consumed by a rule `X -> Marker X`; the marker chooses what it marks, `P(X \| word)` | only its own constituent |
| `feature` | as `schema`, but the result is `Clause[that]`, `Clause[to]`; the governing head's tables are keyed by the marked category | its own constituent **and** the governor |
| `dependent` | an ordinary left `Marker` dependent of the constituent's head, emitted by the split-head tables; a conjunct is any constituent beginning with a coordinator | its head, like any dependent |

Under `schema` and `feature`, markers are never heads and never dependents,
so the "every token heads something" premise disappears: a token is a head
(X-bar) or a marker (MARK), and a gap is not a token at all.  Under
`dependent` the head-outward process decides where a marker goes, and
nothing stops it attaching *and strobe light* as a modifier instead of
building a coordination; that is the failure seen early in this work, and
§8 measures it: 30 of 129 coordination brackets against 48 under `schema`,
although it fills slightly more gaps (21 against 15 of 119).  `feature` is
the version that takes the marker's information seriously, and on 220
trees it pays for that in coverage (unseen marked categories in held-out
folds) without gaining attachment accuracy.  The default is `schema` because it keeps the
most coordination structure on this corpus; the differences are small,
the question stays open, and the switch stays in.

## 5. Gaps: what the corpus does

119 gaps, 112 distinct indices (five indices bind 2–4 gaps each).

* **Gap sites.** Object of a verb (26), subject of a relative clause (22),
  head of a VP, i.e. the inverted auxiliary's canonical slot (19), adjunct in
  a VP (19), subject of a main clause (8), complement (6), stranded
  preposition's object (4), predicative (4), a few others.
* **Binders.** `Prenucleus` (55: fronted `V_aux` 20, `NP` 18, `AdvP` 7, `PP`
  6, `AdjP` 2, …), the head noun of a relativised `Nom` (34), `Postnucleus`
  (21), `Head-Prenucleus` (6), `Det-Head` (3).  Every `Prenucleus` and every
  `Postnucleus` in the corpus is a binder.
* **Locality.** In **117 of 119** cases the binder is a child of the lowest
  node that dominates both binder and gap.  The path from the gap up to that
  node runs through `Head` (258), `Comp` (41), `Mod` (34) and `Coordinate`
  (12) edges.  The two exceptions: *one can never tell when — or even
  whether — Alan was wholly serious* (the fronted *when* sits inside one
  conjunct and binds into the postposed clause) and *no society … of which
  the far greater part of the members are poor* (antecedent inside the
  subject NP, relative clause a clause-level supplement).
* **Order.** The binder precedes the gap in 98 cases; in all 21 cases where
  it follows, the binder is a `Postnucleus`.
* **Coordination and argument sharing.** A gap-to-binder path crosses a
  `Coordination` 12 times, and every time *every* conjunct contains a gap
  with the same index (8 binary, 4 four-way).  This is the across-the-board
  pattern, and it is how the treebank encodes shared arguments: *to develop
  —, build —, flight-test —, and operate — this Earth Moon highway* has one
  `Postnucleus` NP bound to four object gaps; *live — and shop — in the
  area* has one `Postnucleus` PP bound to a complement gap and an adjunct
  gap.  All five multi-gap indices are of this form.
* **How many at once.** 307 nodes have one undischarged gap below them, 19
  have two, none has three.  All 19 are a wh-question with subject–auxiliary
  inversion (*how do you — run a cafe —*), where the inverted-auxiliary gap
  and the fronted-wh gap are open together until two `Prenucleus` layers
  discharge them one after the other.

## 6. Decision C: a gap is a slot for material found elsewhere

A gap marks a place where material from elsewhere in the sentence is
needed: the object of *operate* is the postposed NP, the head of the VP in
*would this — be fine* is the fronted auxiliary, the subject of *live* in
*people that — live* is the head noun.  The treebank writes this as a
binder `(x / NP …)` and a co-indexed `(x / GAP)`, and
`Sentence.with_gaps_filled` copies the binder into the gap.  That copy is
what semantics needs, so the parser must deliver the link, not just a
well-formed bracket.  (An earlier version of this design carried only a
*count* of open gaps; it balanced binders against gaps and could not say
which material went where.  It is gone.)

So the gap is a dependent **of the category of the material it stands
for**: the `--` token enters the chart as `GAP/NP`, `GAP/V_aux`, `GAP/AdvP`,
… and is scored by the ordinary dependent tables (`Obj: GAP/NP`,
`Mod: GAP/AdvP`, the head slot `GAP/V_aux -> Clause`).  Every chart item
carries the categories still missing below it (GPSG `SLASH`; Collins's
1999 Model 3 is the head-driven precedent), and they are discharged by:

1. a `Prenucleus`, `Postnucleus` or `Head-Prenucleus` dependent of exactly
   that category (the binder is itself gap-free);
2. a nominal head (`NP`/`Nom`) taking a clausal dependent that is missing a
   `Nom`: the head noun is the material (relative clauses; `Det-Head`
   binders, 3 cases, are not handled);
3. a `Coordination` is missing `X` only if **every** conjunct is missing
   `X` (across the board): the one postposed NP fills every conjunct's gap.

A complete constituent may be missing material (up to `maxgap` categories,
2 by default for the 19 double-gap nodes) but never holds an unmatched
binder; the root is missing nothing.  On output each binder is co-indexed
with the gap(s) it fills, `fill_gaps` copies the material in, and the
evaluation asks, for every gold gap, whether the parser copied the same
tokens into it.  The linking and filling were checked on hand-built trees
for inversion, a relative clause, across-the-board sharing (one index for
both conjuncts' gaps) and two simultaneous gaps of different categories.

**Gap positions are taken from the input**: the `# sent` line marks each
gap with `--`, so a gap is a token and the chart stays token-indexed.
Predicting gap sites (inserting zero-width items, as Collins does) is the
second step and is where the search space grows; it is to be judged on its
own.

## 7. What the score is, and is not

The chart maximises a product of locally normalised tables, each estimated
by relative frequency:

* `P(C | L)` for every token: the category it projects, with "used as a
  bare dependent" (a gap or a name piece) as one of the outcomes;
* `P(stop | C, side)` and `P(f, D | C, side)` for every head's two
  dependent sequences, `stop + Σ dep = 1` per `(C, side)`; a gap is one
  outcome `(f, GAP/X)` among these.  This is what the program's
  normalisation check verifies, and all it verifies;
* `P(X | marker word)` for every marker: which category it marks;
* per coordination, a geometric number of extra conjuncts and, per
  non-initial conjunct, marked or bare.  (An earlier version also
  multiplied in a conjunct-category prior, a double count; it is gone.)

That product is **not a probability distribution over analyses, and the
tables are not maximum-likelihood estimates of one.**  The gap discipline
of §6 and the like-category requirement of §3 are hard constraints that
rule analyses out, and the tables were normalised without them.  The
argument is the one in Brew (1995), *Stochastic HPSG*, taken up by Abney
(1997): once constraints are in play, the product of locally normalised
relative-frequency tables puts mass on analyses that do not exist, and the
relative frequencies are not the estimates that maximise the likelihood of
the data under the constrained model.  An earlier draft of this note
called the leftover mass a "deficiency" and the arrangement "defensible";
it is neither, and the wording is withdrawn.  The same objection applies
to something the core inherits from `cgel_splithead`: a node's category is
scored twice, by its parent's emission `P(f, D | C, side)` and by its own
projection `P(D | L)`, two overlapping local distributions whose product
was never a distribution, although the split-head note claims "a proper
distribution over analyses" for it.

The remedy is the Model B of `cgel-models.md`, applied to the chart
instead of to a fixed skeleton: a conditional log-linear model over the
chart's analyses of the given string, `P(tree | string) = exp(score) /
Z(string)`, with `Z` computed by an inside pass over the same chart (sum
in place of max), the feature expectations by an outside pass, and the
weights fitted to that normaliser by conditional maximum likelihood from
the relative-frequency start.  `cgel_coordgap_fit.py` does this (design
document §9); the devices of §3, §4 and §6 are the constraints the model
is normalised over, and the overlapping features are no longer a double
count because they are fitted jointly against one normaliser.  The
numbers in §8 that say "relative-frequency weights" are the unfitted
model; "fitted" is Model B.

Fitting on the training sentences of at most 16 tokens (12 epochs, Adam
step 0.05, L2 0.1; 71–80 sentences per fold in the support, 11–16 left
out by extraction and 0–2 by the support check) raises the mean held-in
conditional log-likelihood by about 1.4 nats per sentence and, on *every*
held-out sentence, moves the headline measures in the right direction:
LAS 0.506 → 0.523, UAS 0.572 → 0.592, coordination brackets 47 → 52 of
129, gaps filled with the gold material 14 → 19 of 119, sentences with
every dependency right 4 → 10 (`python3 cgel_coordgap_fit.py --fit`,
about 9 minutes).  Modest, as it must be: the fit re-weights the local
events the chart already has, and the two errors that dominate, valency
and the choice between binders, need features the chart does not yet
carry.

A constraint that was also tried, "a binder is the outermost dependent on
its side" (true of every Prenucleus and Postnucleus in the corpus),
lowered gap filling on the short sentences and was taken out again; under
a properly normalised model it would be a constraint like the others,
not a term to tune.

## 8. Implementation and results (`cgel_coordgap.py`)

Numbers below are on the corrected chart (`cgel-correction-plan.md`:
finiteness classes, the once-only, finite-subject and complement-licensing
rules, CGEL's coordination condition), five-fold cross-validation.  The
chart was rebuilt as an active chart over structured labels in October
2026 (design document §5, §9a), and then made to build each head's right
side before its left so that a left binder never waits (§5.3); with that,
every sentence parses and nothing is excluded.  The rows on the 218
sentences of at most 32 tokens (the two longest were excluded while they
were infeasible) are kept for comparison, as are the first chart's.

```
                                        parsed   LAS    UAS   collapsed  coord.    gaps filled
                                                              bracket F1 brackets  w/ gold material
active chart, right side first, all 220 sentences:
self-fit, relative-frequency weights    219/220  0.558  0.635   0.587     32/130    36/119
5-fold CV, relative-frequency weights   218/220  0.543  0.619   0.571     29/129    31/119

active chart, two-sided chains, ties by late closure, sentences <= 32 tokens (2 excluded):
self-fit, relative-frequency weights    217/218  0.560  0.639   0.594     32/127    36/117
5-fold CV, relative-frequency weights   216/218  0.543  0.622   0.578     29/126    32/117
  COORD off                             118/218  0.516  0.595   0.575      0/6      24/73
  SLASH off (gaps plain tokens)         216/218  0.537  0.615   0.583     29/126     0/117
  ONCE off                              216/218  0.530  0.594   0.589     33/126    20/117
  FINITE off                            216/218  0.519  0.596   0.568     28/126    27/117
  LICENSE off                           216/218  0.521  0.600   0.569     30/126    32/117
  maxgap = 1                            216/218  0.546  0.624   0.579     29/126    34/117
  markers = feature                     212/218  0.550  0.627   0.583     28/123    33/109
  markers = dependent                   216/218  0.540  0.619   0.563     27/126    33/117
5-fold CV, fitted (Model B)             216/218  0.588  0.641   0.595     33/126    41/117
  (right side first, same 218)          216/218  0.543  0.619   0.573     29/126    31/117   unfitted

first chart (ties by loop order; nested coordination inconsistent):
self-fit, relative-frequency weights    217/218  0.556  0.632   0.592     32/127    35/117
5-fold CV, relative-frequency weights   216/218  0.534  0.612   0.579     28/126    29/117
5-fold CV, fitted (Model B)             216/218  0.577  0.628   0.591     32/126    40/117

before the corrections (same folds):    218/220  0.505  0.568   0.587     48/129    15/119
  fitted                                218/220  0.523  0.592   0.593     52/129    19/119

5-fold CV LAS by sentence type (unfitted): coordination+Sdr 0.59 · coordination 0.58 ·
  plain 0.52 · gap+Sdr 0.52 · Sdr 0.51 · coordination+gap+Sdr 0.50 · gap 0.48 ·
  coordination+gap 0.48
```

(`python3 cgel_coordgap.py --eval --ablate`, about 50 minutes;
`python3 cgel_coordgap_fit.py --fit`, about 20 minutes.  The active chart
is slower than the first by about 1.9× on the longest sentences: 106 s
against 57 s on the 32-token one, for the record-valued labels and the
agenda; the state-space reduction of the next step is where the time is.)

How to read this:

* **The active chart is the same model.**  On every sentence of at most
  20 tokens its Viterbi score and log Z equal the first chart's to 1e-9,
  except on ten sentences where only nested coordination differs (a
  coordinator-marked conjunct may now itself be a coordination; a nested
  first conjunct's members are all checked against a common slot).  What
  moved the numbers is **ties**: 86 of the 218 sentences have two Viterbi
  trees of exactly equal score, typically a dependent on a head or inside
  that head's complement of the same category, which no feature
  distinguishes.  The first chart broke them by loop order, which
  happened to attach low; broken by the agenda order alone, LAS fell to
  0.524.  The active chart states the rule (attach as low as possible,
  late closure) and is a point ahead of the first chart.  The rule is a
  default where the model is silent; the feature that would decide it
  (the head's class, lexicalised valency) is the next step.
* **The fit carries over**: on the active chart Model B adds four and a
  half points of LAS held out (0.543 → 0.588) and nine gaps (32 → 41 of
  117), with the same support loss as before (8–13 training sentences
  per fold at extraction, at most one by the gold-above-Z test).

* **The symbolic corrections are worth three to four points of LAS and
  double the gaps filled** at relative-frequency weights (0.505 → 0.534
  on the first chart, 0.543 on the active one; 15 → 29, 32 of 117), and
  each rule earns its place in the ablation: the finite-subject rule
  alone is worth two and a half points, the licensing rule two, the
  once-only rule one and a half, the gap discipline half a point on LAS
  but all of the gap filling.  One open gap instead of two costs nothing
  on this corpus (0.546 against 0.543, within the noise), which bears on
  the state-space step.
* **Coordination brackets fell** from 48 to 28 of 129: CGEL's condition
  admits more coordinations and the unfitted weights rank them badly; the
  fit recovers some (32) and the rest is the next thing to look at.
* **The fit now does what Model B is for**: on the corrected chart it adds
  four points of LAS held out (0.534 → 0.577) and eleven gaps (29 → 40),
  twice what it added on the uncorrected chart, because the constraints it
  is normalised over are now the right ones.  Support: 8–13 training
  sentences per fold fall out at extraction (a coordination heading a
  phrase), at most one more by the gold-above-Z test.
* **Gap sentences remain the hardest** (0.48–0.50 by type).  The two
  longest sentences (38 and 33 tokens), excluded while the chart's
  gap–binder state product made them infeasible, now parse in under a
  minute (design document §5.6); the numbers on all 220 are the headline.
* **Markers**: the three settings are within 0.013 LAS; `feature` is
  slightly best and loses four sentences of coverage.  Still open.

Tests: `python3 tests/cgel_coordgap.test.py` (12 tests, about 15 s:
per-table normalisation, markers never heads or dependents in `schema`
mode, every gap accounted for, token preservation on the short sentences,
coordination shape, marker placement, every gap bound to material of its
category, filling restores *this would be*, across-the-board sharing with
one index per coordination, a lone gap has no parse, the COORD switch, all
three marker modes run).

## 9. Why these devices and not something more general

* Each is stated in a line or two and matches a corpus regularity with a
  counted exception list (14 of 131 coordinations plus the 29
  coordination-headed phrases, 2 of 119 binders, 19 of 326 gap-carrying
  nodes).
* None touches the head-driven core: COORD is built from complete
  constituents; the gap categories are a key on existing cells; the marker
  treatment is a switch.
* Each failure is diagnosable by name (unlike-category, coordination as
  head, wrong gap category, non-local binder, marker mode) rather than by a
  probability being low.

Not done: a general n-ary PCFG for coordination (220 trees cannot support
it, as `cgel_cyk.py` showed), unlike-category unification, gap-site
prediction, valency, and a repair of the inherited double count.
