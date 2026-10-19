# Design of `cgel_coordgap.py`

This document describes the parser as built: its representations, the
extraction of events from treebank trees, the tables, the chart algorithm
and its invariants, the reconstruction of output trees, gap linking and
filling, the evaluation, and the status of the scoring function.  It is the
reference for the implementation; `cgel-coordination-gaps.md` is the
companion note with the corpus survey, the design decisions in context,
and the measured results.

## 1. Purpose and scope

The parser extends the head-driven (Eisner/Collins-style) CYK parser of
`cgel_headcyk.py` so that it covers the three parts of the CGEL treebank
that a head-driven process does not describe:

* **coordination**, which has no head;
* **marker tokens** (subordinators `Sdr`, coordinators `Coordinator`),
  which are neither heads nor, on the default setting, dependents;
* **gaps**, which are places where material found elsewhere in the
  sentence is needed, written in the treebank as a binder `(x / NP …)` and
  a co-indexed `(x / GAP)`.

The output is a treebank-style tree: categories, function labels on every
edge, `Coordination` nodes with `Coordinate` children, markers as first
children of what they mark, and every gap co-indexed with the binder whose
material fills it, so that `fill_gaps` (the parser's counterpart of
`Sentence.with_gaps_filled`) produces the structure semantics needs.

Out of scope, stated here and counted in the note: predicting gap
*positions* (they are read from the input), unlike-category coordination,
a `Coordination` as the head of a larger phrase, `Det-Head` binders, the
two non-local binders in the corpus, and a properly normalised probability
model (§9).

## 2. Representations

### 2.1 Input

A sentence is a sequence of token categories `ts[0..n)` with parallel
surface words.  Both come from the gold tree's leaves in surface order
(`sentence_tokens`, `sentence_words`), which by the reader's validated
invariant is exactly the `# sent` line: a lexical category per word and
the token `GAP` at every `--`.  The parser therefore knows *where* gaps
are, not what they stand for.

### 2.2 Chart categories

Chart categories are strings:

| form | meaning |
|---|---|
| `Clause`, `NP`, `VP`, … | a folded constituent (§3.1) of that treebank category |
| `N`, `D`, … | a bare lexical token used as a dependent (a `Flat` name piece) |
| `GAP/X` | a gap token standing for material of category `X` |
| `Clause[that]`, `VP[to]` | (`markers="feature"` only) a constituent marked by that subordinator |
| `Coordination` | a coordination of like conjuncts |

`X` in `GAP/X` ranges over the *binder categories* observed in the
treebank (`Grammar.gapcats`), normalised by `binder_category`: a head-noun
binder (`N`, `N_pro`, `Nom`) supplies a `Nom`; a `Coordination` binder
supplies its conjuncts' category; every other binder supplies its own
category.  On the corpus the set is `AdjP AdvP Clause DP NP Nom PP VP
V_aux`.

### 2.3 Output tree

`cgel_reader.Node` objects: `cat`, `edge` (function label), `index`,
`feats`, `children`.  A gap is `Node(cat="GAP", feats={"for": [X]})` with
an `index` shared with its binder after linking.  Markers are
`Node(cat="Sdr"|"Coordinator", edge="Marker", feats={"t": [word]})`.
`render` prints this compactly; the reader's `pretty` prints it in
treebank layout.

## 3. Extraction (`iter_events`)

The extractor turns each gold tree into the events the tables are
estimated from.  It runs once per training sentence and is deterministic.

### 3.1 Folded head chains

A **head chain** is a node followed down its head edges (`Head`,
`Det-Head`, `Mod-Head`, `Marker-Head`) to a lexical token or a gap
(`head_chain`).  A `Flat` container (an `N` or `D` without its own
token whose children are all `Flat`) continues the chain into its first
piece; the other pieces become `Flat` dependents.  The **top** of a chain
is a node that is not itself the head child of its parent.

Every top node with a chain becomes one **folded constituent**: category
`C` = the top's category, head `L` = the lexical category at the bottom
(or `GAP/X` when the bottom is a gap: an inverted auxiliary's slot), and
dependents = all non-head, non-chain children of every node on the chain,
each with its function label and its category, divided into a *left*
sequence (ordered outward from the head) and a *right* sequence (ordered
outward), by token span relative to the head token.  Gap children get
category `GAP/X` from their binder.

A chain top whose chain ends nowhere (its head is a `Coordination`, a
headless `Nom`, a `Compounding` nominal, or the `Marker-Head` *etc.*) is
reported as a `skip` event and not modelled; the counts are printed by
`--eval`.

### 3.1a What happens to unary chains, and why

In the treebank a head projects through one or more levels: `N → Nom →
NP`, `V → VP → Clause`, `D → DP → Nom → NP` for a fused determiner-head,
`V → VP → Clause_rel → Clause_rel` for a marked relative clause.  Each
level is a node of its own and each takes its own dependents: the subject
attaches at `Clause`, the object at `VP`, a determiner at `NP`, an
adjective at `Nom`.  Over the corpus the 3,094 folded constituents have
chains of 2 to 7 categories (head word included): 1,280 of length 2,
1,235 of length 3, 468 of length 4, 111 longer.

The chart does not build these levels.  **Every chain is folded into one
item**: its category is the top of the chain, its head is the token at the
bottom, and its dependents are the dependents of every level, pooled into
one left and one right sequence.  The chain itself and the level at which
each function attaches are recorded as side tables and used only to
unfold the output.

Why fold rather than parse the levels:

1. *Consistency between tables and chart.*  The earlier parser
   (`cgel_headcyk.py`) folded chains in the chart but estimated its tables
   from the unfolded trees, so a `V` projecting `Clause` could only take
   `Clause`-level dependents: no object, because objects are `VP`-level.
   Its parses were VP-rooted and subjectless.  Folding at extraction
   makes the tables describe the items the chart builds.
2. *The head-driven process has nothing to decide at a unary level.*  A
   projection `N → Nom → NP` adds no token and no attachment; which
   levels exist is a function of the head's class and of which
   dependents it took.  Treating it as a parsing decision would add unary
   rules to the chart and ambiguity without information.
3. *It is what the split-head model already assumed.*  Its generative
   story is "a head projects a category and takes dependents"; the
   per-node events it extracted from unfolded trees were a mismatch with
   that story, as (1) shows.

What unfolding can and cannot recover.  The most frequent chain for a
`(top category, head class)` pair reproduces the gold chain for 82% of
folded constituents; the most frequent attachment level for a function
reproduces the gold level for 97% of dependents.  The misses are the
cases where the same pair of categories has more than one chain
(`Clause → Clause → VP` for an inverted clause against `Clause → VP`;
`NP → NP → Nom` for a genitive determiner) and where a function attaches
at more than one level, chiefly `Mod` under `Clause` against `VP` (37
cases) and `Mod` under `NP` against `Nom` (13).  Those are decisions the
parser never makes; the unfolding guesses them by frequency.

Consequence for evaluation.  Every reconstructed level is a bracket, and
on a one-word phrase (`(NP (Nom (N_pro it)))`) two brackets are produced
by table lookup, not by parsing.  A bracket measure that counts every
level therefore rewards and punishes the lookup: in a corpus-wide error
analysis of such a measure, 29% of the spurious brackets were
single-token layers and 18% label disagreements on a correct span
(mostly `NP` against `Nom`), while 83% of the *missed* brackets were
spans absent from the parse, i.e. attachment errors.  That is why §8
makes labelled attachment the headline, counts each span once for the
constituency measure, and does not report a per-level bracket score at
all.  The
folded representation is also why the parser is, in effect, a dependency
parser with projection categories: CGEL's headed constituents with
function labels are a labelled dependency tree plus projections, and the
chain is the projection.

### 3.2 Events

| event | emitted for | used for |
|---|---|---|
| `proj C L left right chain levels` | every folded constituent | `P(C \| L)`, the two dependent sequences, the chain and attachment-level tables |
| `leaf D` | every bare token used as a dependent (a gap `GAP/X`, a `Flat` piece) | the `<leaf>` outcome of `P(· \| D)` |
| `mark kind word X is_conjunct` | every `Sdr`/`Coordinator` in a `Marker` slot; `X` is the category of the chain top it sits on | `P(X \| word)` |
| `coord X n bare` | every `Coordination` with ≥ 2 `Coordinate` children | the conjunct-category support, `p_more`, `p_bare` |
| `skip C` | an unfoldable top | reporting |

### 3.3 Marker modes

`markers` (a `Grammar` argument) decides how a `Marker` child enters the
`proj` events:

* `schema` (default): it is skipped as a dependent and recorded only as a
  `mark` event;
* `feature`: as `schema`, and in addition every non-lexical dependent that
  carries an `Sdr` marker somewhere on its head chain gets the category
  `D[word]` instead of `D`, so the governing head's tables see the marker;
* `dependent`: it is an ordinary dependent `(Marker, Sdr|Coordinator)` and
  also a `leaf` event, so the token can be emitted by the split-head
  tables.

## 4. Tables (`Grammar`)

All tables are relative frequencies with add-α smoothing over the
observed support (`_smooth`, α = 1 by default).

| table | key → distribution over | support |
|---|---|---|
| `proj[L]` | head category `L` → projected category `C`, including `<leaf>` | observed `(L, C)` pairs |
| `stop[(C, side)]`, `dep[(C, side)]` | one stopped sequence per side: `stop + Σ_(f,D) dep = 1` | observed `(f, D)` on that side |
| `emit[(C, side)][D]` | the same `dep` table indexed by dependent category: list of `(f, p)` | derived |
| `mark[(kind, word)]`, `mark_kind[kind]` | marker → category marked, with back-off from word to class | observed |
| `coord_cat` | conjunct categories observed (used only as a support set) | observed |
| `p_more`, `p_bare` | scalar: another conjunct after the second; a non-initial conjunct without a marker | — |
| `chain[(C, L)]` | most frequent head chain for a folded category | deterministic |
| `level[(C, f, word?)]` | most frequent chain level at which function `f` attaches (word-specific for `Marker`) | deterministic |
| `gapcats` | the `X` of every `GAP/X` seen | set |

`check_normalization` verifies `stop + Σ dep = 1` per `(C, side)`.  It
verifies nothing else (§9).

## 5. The chart (`parse`)

### 5.1 Cells and keys

Five tables of cells over spans, each a dict from key to
`(score, backpointer)`, keeping only the best entry per key (Viterbi):

| cell | span | content |
|---|---|---|
| `left[i][h]` | `[i, h)` | head at `h`, left dependents attached outward over `[i, h)` |
| `right[h][k]` | `(h, k)` | head at `h`, right dependents over `(h, k)` |
| `arg[i][k]` | `[i, k)` | a complete constituent |
| `conj[i][k]` | `[i, k)` | a `Coordinator`-marked conjunct |
| `tail[i][k]` | `[i, k)` | one or more conjuncts, the last one marked |

Keys are `(C, gaps, binders)`:

* `C` is the chart category (§2.2);
* `gaps` is the sorted tuple of categories `X` still missing below the
  item: material that a binder of category `X` has yet to supply;
* `binders` is the sorted tuple of binder categories attached on this
  side chain whose gap lies on the *other* side of the head (or in the
  head slot); it is non-empty only in `left`/`right` cells and is always
  empty on a complete constituent;
* side keys carry a fourth element, the once-only functions already
  attached on that side.

Both tuples are bounded by `maxgap` (2 by default).  With
`slash=False` both are always empty.

### 5.2 Invariants

1. Every `arg`, `conj` and `tail` key has `binders == ()`.
2. A root is an `arg[0][n]` (or `conj[0][n]`) key with `gaps == ()` and a
   root-eligible category.
3. A binder dependent (`Prenucleus`, `Postnucleus`, `Head-Prenucleus`) is
   itself gap-free (`gd == ()`).
4. A `Coordination` key's `gaps` equals the `gaps` of each of its
   conjuncts (across the board); conjuncts share the whole key, so in
   `feature` mode they also share the marker feature.
5. Every surface token is used exactly once: as a head, as a bare leaf
   dependent, or as a marker consumed by MARK/conj.  (Checked by the
   tests on output trees.)
6. Every dependency computed at footprint `F` uses only cells of smaller
   footprint or cells of footprint `F` computed earlier in the same
   iteration (§5.4).

### 5.3 Rules

Scores are log-probabilities; `+` below is in log space.

**Base (F = 0).**  For each token `h`:
`left[h][h][(C, g0, ())] = log P(C | L) + log stop_L(C)` and
`right[h][h+1][(C, (), ())] = log stop_R(C)` for every projected `C ≠
<leaf>`.  For an ordinary token `L = ts[h]`, `g0 = ()`.  For a gap token
there is one base per `X ∈ gapcats` with `L = GAP/X` and `g0 = (X,)`: the
gap is the head slot (an inverted auxiliary) and the item is missing an
`X`.  Marker tokens get no base: they are never heads.

**Leaf (F = 1).**  A gap token gives `arg[i][i+1][(GAP/X, (X,), ())] =
log P(<leaf> | GAP/X)` for every `X` with that outcome; a lexical token
gives `arg[i][i+1][(L, (), ())] = log P(<leaf> | L)` when `L` has a
`<leaf>` outcome (name pieces).

**Attach (left and right chains).**  `attach(C, side, …)` extends a chain
item `(C, g0, b0, used)` by one complete dependent `(D, gd, ())` with
function `f` and emission `P(f, D | C, side)`, subject to four structural
rules, each a switch for ablation: `once` (a head takes `Subj`, `Det`,
`Obj`, `PredComp` at most once; `used` on the side key records which it
has), `finite` (a `Subj` only on a finite head: `V:fin`, `V_aux:fin`,
`V_aux:mod`, or the inverted-auxiliary slot), `license` (a complement
function only on a head class the treebank shows taking it), and, for a
coordination dependent, every member category licensed for `f`.  Then:

```
gaps, binders = g0 + gd, b0
if f is a binder function:
    require gd == ()                      # a binder is gap-free
    X = D without any [feature]
    if X in gaps: remove one X from gaps  # fills a gap already below
    else:         add X to binders        # its gap is on the other side
elif C in {NP, Nom} and D is clausal and "Nom" in gd:
    remove one "Nom" from gaps            # the head noun is the material
require len(gaps) <= maxgap and len(binders) <= maxgap
```

The nominal rule is what binds a relative clause: the clausal dependent
is missing a nominal, and the head noun of the phrase it attaches to
supplies it.

**Head combination.**  `arg[i][k][(C, gaps, ())]` from `left[i][h][(C,
gl, bl)]` and `right[h][k][(C, gr, br)]`: `gaps, binders = cancel(gl +
gr, bl + br)` where `cancel` removes each pending binder together with an
open gap of the same category; require `binders == ()` (no binder without
a gap) and `len(gaps) ≤ maxgap`.  This is where a `Prenucleus` on the left
meets a gap on the right or in the head slot, and a `Postnucleus` on the
right meets a gap on the left.

**MARK (subordinator).**  If `ts[i] == Sdr` and `F ≥ 2`, for every
`arg[i+1][k][(X, gx, ())]`: `arg[i][k][(X', gx, ())] = score + log P(X |
word)`, where `X' = X` (`schema`) or `X[word]` (`feature`).  Not applied
in `dependent` mode.  Gaps pass through unchanged.

**conj (coordinator-marked conjunct).**  If `ts[i] == Coordinator` and
`F ≥ 2`: in `schema`/`feature` mode, from every `arg[i+1][k]` key with
`log P(X | word) + log(1 − p_bare)`; in `dependent` mode the marker is
already inside `arg[i][k]`, which becomes the conjunct with `log(1 −
p_bare)`.

**tail.**  `tail[i][k][key]` is either a single final conjunct
(`conj[i][k][key] + log(1 − p_more)`) or a conjunct followed by a tail
with the same key: `conj[i][m] + tail[m][k] + log p_more`, or a bare
non-final conjunct `arg[i][m] + log p_bare + tail[m][k] + log p_more`
(a `Coordination` may not be a bare middle conjunct, to avoid
left-recursive duplicates).

**COORD.**  `arg[i][k][(Coordination/cats, gaps, ())]` from a first
conjunct `(X, gaps, ())` and a tail with the same `gaps` (across the
board); `cats` is the set of the conjuncts' categories, carried in the
chart category (`Coordination/NP+PP`) while the tree node is plain
`Coordination`.  The conjuncts need not share a category: CGEL's condition
(ch. 15 §3.1) is likeness of *function*, and it is enforced where the
coordination is attached (**Attach** below) by requiring every member
category to be licensed in the slot it fills.  A coordination at the root
needs every member rootable.  No further term is added (§9).

**Root.**  The best `arg[0][n]` key with `gaps == ()` and base category in
`ROOT_CATS`; or, outside `dependent` mode, the best such `conj[0][n]` key
(a clause-initial *and*/*but*/*so*).

### 5.4 Loop order

For footprint `F = 1 … n`, in this order: all `arg[i][i+F)` cells (leaf,
head combination, MARK, COORD), then `conj` and `tail` cells of footprint
`F`, then `left` chains with `h − i = F`, then `right` chains with `k − h
− 1 = F`.  Head combination at `F` uses `left`/`right` of smaller
footprint; MARK uses `arg` of footprint `F − 1`; COORD uses `arg` and
`tail` of smaller footprint; `tail` at `F` uses `conj` at `F` (computed
just before) and smaller cells; the chains at `F` use `arg` of footprint
`≤ F` (computed earlier in the same iteration) and chains of smaller
footprint.

### 5.5 Complexity

Per footprint the work is cubic in `n` times the number of key pairs
examined per cell.  Keys multiply with the gap tuples, so sentences with
several gap tokens are the slow ones: the 36-token right-node-raising
sentence takes about 15 s, the median sentence well under 0.1 s, the
whole corpus a few minutes per configuration.  The tests restrict
corpus-wide checks to sentences of at most 12 tokens.

## 6. Reconstruction (`_Rebuilder`)

### 6.1 Backpointers

| cell / rule | backpointer |
|---|---|
| base | `("base", L)` (L may be `GAP/X`) |
| leaf | `("leaf", X or None)` |
| attach | `(m, dependent key, f, inner key)` |
| head combination | `("head", h, left key, right key)` |
| MARK | `("mark", X, gaps)` |
| COORD | `("coord", m, conjunct key)` |
| conj | `("conj", body key)` or `("conj-arg",)` |
| tail | `("last",)` or `("more", m, "conj"|"arg")` |

`chain_deps` walks a side chain back to the base, collecting `(f, node)`
in surface order; `_base_key` recovers the base key (and so the head's
`L`, needed to pick the chain for expansion).

### 6.2 Unary re-expansion (`expand`)

A folded constituent `(C, L)` is unfolded into the most frequent chain
for that pair, e.g. `(Clause, V) → Clause, VP, V`.  Each dependent is
assigned the chain level recorded for its function (`level[(C, f)]`,
word-specific for markers).  Assignment is made **outward-monotone**:
walking away from the head on each side, a dependent may never attach
lower than one nearer the head (the running minimum of levels), which
keeps surface order intact when nesting.  `Flat` pieces attach at the
lexical level, inside the container node.  The head token becomes the
`Head` leaf of the lowest chain node.

### 6.3 Marker placement (`expand_marked`)

A subordinator is inserted as the first child of the chain node recorded
for that word (`to` → `VP`, `that` → `Clause`), found by descending `Head`
children from the top of the marked body; the body's top node is
returned, so the marked constituent keeps its folded category.  A
coordinator is placed as the first child of a new node of the conjunct's
category whose `Head` is the body: `(Nom :Marker (Coordinator and) :Head
(Nom …))`, as in the treebank.

## 7. Gap linking and filling

### 7.1 `link_gaps`

After reconstruction, binders and gaps are co-indexed by a single
bottom-up pass that applies the chart's discharge rules to the finished
tree:

* a gap node contributes an open gap `(X, [node])`;
* a `Coordination` merges its conjuncts' open gaps by category into one
  open gap with several nodes (across the board);
* at any other node, the open gaps of all children are collected; then
  for each child in a binder function (`Prenucleus`, `Postnucleus`,
  `Head-Prenucleus`) of category `X`, the first open gap of category `X`
  (in child order, depth first) is bound to it; then, if the node is `NP`
  or `Nom` with a clausal child, its `Head` child is bound to the first
  open `Nom` gap;
* remaining open gaps propagate upward.

Indices are fresh labels `g1, g2, …`.  The chart guarantees that every
gap is discharged by a binder of its category somewhere above it, so the
pass binds every gap; a test checks that every gap in every parse of the
short sentences is bound to a binder of the category the gap stands for.
Where two open gaps share a category under one binder, the chart's
tuples carry no identity, and the pass pairs the *first* one; that is a
convention, not something the score decided.

### 7.2 `fill_gaps`

Returns a copy of the tree in which every indexed gap is replaced by a
deep copy of its binder's subtree, recursively (a binder may itself
contain gaps), with the gap's function label on the copy.  This is the
parser's counterpart of `Sentence.with_gaps_filled` and the structure in
which the postposed NP appears as the object of each coordinated verb and
the fronted auxiliary appears as the head of its VP.

## 8. Evaluation (`evaluate`, `summarize`, `cross_validate`)

CGEL trees are headed constituents with function labels, which is a
labelled dependency tree plus projection categories.  The evaluation
follows that: a dependency measure first, a constituency measure that
does not count the projection levels, and the gap-filling measure for
the shared material.  Gold and parsed trees go through the same
conversions.

| measure | definition |
|---|---|
| **LAS** (headline) | labelled attachment: tokens (gaps included, root excluded) whose head token *and* function label are right.  `dependencies` reads them off a headed tree: a token depends on the head of the parent of the highest constituent it heads, with that constituent's function; a marker depends on the head of what it marks (`Marker`); a non-initial conjunct on the first conjunct's head (`Coordinate`); `head_token` follows head chains, a `Flat` container to its first piece, a `Coordination` to its first conjunct |
| UAS | the same with the head token only |
| collapsed-bracket F1 | spans counted once, a span correct if the predicted and gold label sets at that span intersect (`collapsed_brackets`): the constituency measure without the unary layers |
| coordination brackets | gold `Coordination` brackets recovered |
| gaps filled with the gold material | gold gaps whose predicted binder covers exactly the gold binder's token span (`gap_bindings`) |
| all-dependencies-right, root-match | sentences with every dependency right; root category equality |

Coverage is reported separately; LAS and UAS are micro-averaged over
tokens, the F1 measure averaged over parsed sentences.  A per-level
labelled bracket F1 is deliberately not reported: it would mostly
measure the unfolding tables of §6.2, and the earlier parser it would be
compared with has no function labels, so the comparison would not be
worth the risk of someone adopting the number.  `cross_validate` uses a fixed shuffle (seed 0) into five
folds.  `--ablate`
re-runs the cross-validation with `coord=False`, `slash=False`,
`maxgap=1`, `markers="feature"`, `markers="dependent"`.

## 9. The probability model: Model B over the chart

The chart is driven by a feature-weighted score.  Every edge of every
rule in §5.3 carries a list of features (`feature_weights` names them:
`proj`, `leaf`, `stop`, `dep`, `mark`/`markk`, `conj`, `coord`), its
weight is the sum of their weights, and the `Chart` class runs the same
rule loops in either of two semirings: `max` (Viterbi, with
backpointers) or `sum` (inside masses, with every edge recorded for an
outside pass).  The weights are initialised to the log relative
frequencies of the tables in §4, so the untrained model is the parser
described above.

That alone does not make the score a probability: with the gap
discipline, the like-category rule and the root condition as hard
constraints, a product of locally normalised tables puts mass on
analyses that do not exist and its relative frequencies are not the
maximum-likelihood estimates of any model over the analyses that do
(Brew 1995; Abney 1997).  `cgel_coordgap_fit.py` is the remedy, and it
is the Model B of `cgel-models.md` applied to the chart instead of to a
fixed skeleton:

    P(analysis | string) = exp( Σ_f w_f · count_f(analysis) ) / Z(string)
    Z(string) = Σ over the chart's analyses of the string

* `inside` runs the chart in the sum semiring and returns `log Z`;
* `outside` propagates outside masses over the recorded edges in reverse
  creation order (which is reverse topological order) and accumulates the
  expected count of every feature, exactly; a finite-difference check of
  `∂ log Z / ∂ w_f` against `E[count_f]` is in the tests and the `--check`
  command;
* `gold_features` reads the treebank analysis's feature counts off the
  same extraction the tables came from, and `loglik` is
  `Σ w·count(gold) − log Z`;
* `fit` does conditional maximum likelihood by Adam on
  `Σ_s [count(gold_s) − E[count | string_s]] − λ (w − w_0)`, an L2 pull
  towards the relative-frequency start `w_0`.

The support is the chart's.  A treebank analysis is in it only if the
extractor folds every node (no `Coordination` as a head), every
coordination has like conjuncts and nothing but conjuncts inside, every
gap is bound by a `Prenucleus`/`Postnucleus`/`Head-Prenucleus` or by a
nominal head (a fused `Det-Head` counts as one), and every feature it
uses exists; `gold_features` checks the extraction-level conditions and
`fit`/`loglik` apply the decisive test, that the gold score does not
exceed `log Z`.  With the grammar built on all 220 trees, 168 analyses
pass the extraction-level test; among the 113 sentences of at most 16
tokens, 95 have a defined conditional likelihood.  Sentences outside the
support are not trained on and are counted in the output.

Two consequences.  The overlapping features (a node's category in its
parent's `dep` feature and in its own `proj` feature) stop being a double
count: they are two features of one log-linear model with one
normaliser, fitted jointly.  And the constraints are now what the model
is normalised over rather than something it ignores, which is exactly
Model B's restriction to conforming analyses.  What is *not* changed is
the feature set: the fitted model can only re-weight the local events
the chart already has, so valency and binder locality, which §8 and the
note identify as the missing information, still have to be added as
features before fitting can act on them.

Cost: inside and outside each cost what a Viterbi pass does, plus the
recorded edges; training is therefore restricted to sentences of at most
`--maxtok` tokens (16 by default), while evaluation uses every sentence.
Result (5-fold CV, 12 epochs): LAS 0.506 → 0.523, UAS 0.572 → 0.592,
coordination brackets 47 → 52 of 129, gaps filled 14 → 19 of 119.

## 10. Switches

| switch | where | default | effect |
|---|---|---|---|
| `markers` | `build_grammar` | `schema` | §3.3 |
| `maxgap` | `parse` | 2 | bound on open gaps and pending binders |
| `coord` | `parse` | `True` | COORD rule on/off |
| `slash` | `parse` | `True` | gap tuples kept/zeroed (gaps become plain tokens) |
| `once`, `finite`, `license` | `parse` | `True` | the structural rules of §5.3 **Attach** |
| `alpha` | `build_grammar` | 1.0 | smoothing of the initial weights |
| `--maxtok`, `--epochs`, `--lr`, `--l2` | `cgel_coordgap_fit.py --fit` | 16, 10, 0.05, 0.1 | training-set length bound, epochs, Adam step, L2 pull towards the start |

## 11. Tried and dropped

* **A count of open gaps** instead of their categories.  It balanced
  binders against gaps but could not say which material fills which gap;
  replaced by categories so that the output carries the link.
* **A conjunct-category prior** on COORD.  A double count of what the
  conjuncts' own projections already score; removed.
* **"A binder closes its side"** (no further dependents outside a
  `Prenucleus`/`Postnucleus`), true of every such binder in the corpus.
  Lowered gap filling on the short sentences; removed.  Under a properly
  normalised model it would return as a constraint.
* **A valency frame feature** (the multiset of a head's argument
  functions, keyed by the folded category).  Not lexicalised, pooled the
  X-bar levels, and in its unbounded form multiplied the chart's keys by
  sixty at ten tokens; bounded to attested frames it still coupled
  independent decisions.  Replaced by the structural rules of §5.3.
* **Like-category coordination.**  Replaced by CGEL's like-function
  condition (§5.3 COORD), which brings the unlike-category cases into the
  support.
* **Markers as leaf dependents** of the split-head tables as the default.
  Kept as `markers="dependent"` for comparison; it builds fewer
  coordination brackets (30 against 48 of 129 under cross-validation),
  because the parser may attach *and X* as a modifier instead, while
  filling slightly more gaps (21 against 15 of 119).

## 12. Tests (`tests/cgel_coordgap.test.py`, `tests/cgel_coordgap_fit.test.py`)

The fit tests (six, a few seconds): `log Z` is at least the Viterbi
score; the partition of a one-token string equals the hand-computed sum;
expected counts match finite differences of `log Z`; the stop and leaf
expectations add up to the token count; where the Viterbi parse has every
dependency right its score equals the gold feature score, and the gold
score never exceeds `log Z` on the support; three epochs of fitting raise
the conditional likelihood of the training sentences.

Twelve tests, about 15 s: per-side normalisation and per-head projection
normalisation; markers never heads or dependents in `schema` mode; every
gap accounted for by an event or a reported skip; every parse of a short
sentence preserves its tokens and gap count; coordination output shape
(like conjuncts, marker first in the last conjunct); a subordinator sits
first in a clause or VP; every gap in every short parse is bound to a
binder of its category; filling *would this — be fine* puts *would* at
the VP head; across-the-board sharing gives one index per coordination;
a lone gap has no parse while `V_aux GAP` forces the auxiliary into
`Prenucleus`; the COORD switch; all three marker modes run and normalise.
The linking and filling pass was also exercised on hand-built trees for
inversion, a relative clause, shared objects and two simultaneous gaps.
