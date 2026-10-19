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

Not covered, deliberately: unlike-category coordination (9 of 131; a parse
is produced with a wrong label), initial-marker correlatives (3), a
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

Besides the three devices, three choices keep the output comparable to the
treebank: function labels are kept in the emission tables (so binders are
identifiable and every dependent in the output carries its function);
unary head chains are folded at extraction (`Clause -> VP -> V` is one
constituent headed by `V` with all the chain's dependents) and re-expanded
on output with per-function attachment levels learnt from the corpus; and a
`Flat` name is headed by its first piece.  The headline measure is labelled
attachment (LAS: head token and function label right, gaps included), the
natural measure for headed constituents with function labels; UAS drops
the label; collapsed-bracket F1 counts each span once, so that the unary
projection levels, which the parser reconstructs by table lookup (design
document §3.1a), are not scored; "gaps filled" counts gold gaps into which
the parser copied exactly the gold material.  No per-level bracket score
is reported, and no comparison with the earlier parser, which has no
function labels.

```
                                  parsed   LAS    UAS   collapsed  coord.    gaps filled
                                                        bracket F1 brackets  w/ gold material
cgel_coordgap, self-fit           218/220  0.517  0.585   0.596     49/129    22/119
cgel_coordgap, 5-fold CV          218/220  0.505  0.568   0.587     48/129    15/119
  COORD off                       118/220  0.453  0.519   0.569      0/6      12/73
  SLASH off (gaps plain tokens)   218/220  0.501  0.557   0.596     48/129     0/119
  maxgap = 1                      218/220  0.506  0.570   0.585     48/129    17/119
  markers = feature               214/220  0.506  0.575   0.584     47/126    18/111
  markers = dependent             218/220  0.493  0.560   0.576     30/129    21/119
fitted, Model B over the chart   218/220  0.523  0.592   0.593     52/129    19/119
  (its own run of the folds,
   unfitted on the same folds)   218/220  0.506  0.572   0.587     47/129    14/119

5-fold CV LAS by sentence type:  coordination only 0.61 · coordination+Sdr 0.59 ·
  Sdr only 0.49 · plain 0.48 · gap+Sdr 0.44 · coordination+gap+Sdr 0.46 ·
  gap only 0.39 · coordination+gap 0.39
```

(`python3 cgel_coordgap.py --eval --ablate`, about 7 minutes; the fitted
rows from `python3 cgel_coordgap_fit.py --fit`, §7.)

How to read this honestly:

* **Coverage** is the clear result: 218 of 220.  The two failures are
  *and why* (unlike-category coordination) and *etc.* (`Marker-Head`), both
  on the exception list.
* **Half the tokens get the right head and function.**  LAS 0.51 means one
  token in two is attached to the wrong head or with the wrong function;
  UAS 0.57 says most of that is the head, not the label.  Sentences with
  gaps are the worst (0.39–0.46), plain sentences are not the best (0.48):
  the attachment problem is general, and the side tables, which let a verb
  take several subjects or objects and decide prepositional and clausal
  attachment by frequency alone, are where it comes from.
* **COORD** is worth 0.05 LAS on the sentences it reaches and all of the
  coverage of the 100 coordinator sentences.  It builds a third of the gold
  coordination brackets; the misses are mostly the 29
  `Coordination`-as-head cases and *and X* taken as a conjunct of the
  nearest NP rather than the right one.
* **Gap filling is where the work is.**  The mechanism delivers a binder
  of the right category for every gap in every parse (a test checks this),
  but the parser copies the *gold* material into only 15 of 119 gaps under
  cross-validation; without the discipline it copies none, and LAS hardly
  moves (0.501 against 0.505).  On the 17 short gap sentences the misses
  were classified one by one: every one is the parser choosing the wrong
  category for what the gap stands for, most often taking an in-situ
  auxiliary as fronted (`V_aux` for `NP`) or the reverse.  Nothing in the
  tables prefers the right pairing when two binders and two gaps are in
  play.  Valency and a preference for the nearest binder of the right
  category are the next things to add, and they are additions to the
  scoring, which §7 says needs rebuilding anyway.
* **maxgap** 2 against 1 makes no difference; 2 is kept for the 19
  double-gap nodes.
* **Markers**: see §4.  The three settings are within 0.013 LAS of each
  other; they differ on coordination brackets (`dependent` 30, the others
  47–48) and slightly on gap filling.  Nothing here settles what a marker
  should tell the rest of the tree.

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
