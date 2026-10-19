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

A chart category is a record, `Cat(key, base, form, gap, marker)`, built
by `cat(...)` or parsed once from a table string by `Cat.parse`:

| key (the table string) | record | meaning |
|---|---|---|
| `Clause`, `NP`, `VP`, … | `base` | a folded constituent (§3.1) of that treebank category |
| `N`, `D`, … | `base` | a bare lexical token used as a dependent (a `Flat` name piece) |
| `V:fin`, `V_aux:mod` | `base`, `form` | a verb or auxiliary with its finiteness class (a data intervention, `load_corpus`) |
| `GAP/X` | `base = GAP`, `gap = X` | a gap token standing for material of category `X` |
| `Clause[that]`, `VP[to]` | `base`, `marker` | (`markers="feature"` only) a constituent marked by that subordinator |
| `NP+PP` | `base` | a fused category of the treebank, atomic here |
| `Coordination` | `base` | a coordination; its conjuncts' categories live in the edge label (§5.1), not in the category |

The tables (§4) are keyed by the strings the extractor produces; `key`
is that string, stored once, and is the only place the chart meets it.
Every rule compares fields: a binder supplies its `base`, a finite head
is one whose `base`/`form` is in `FINITE`, a root is a `base` in
`ROOT_CATS`.  Nothing downstream of the extractor parses a string.

`X` in `GAP/X` ranges over the *binder categories* observed in the
treebank (`Grammar.gapcats`), normalised by `binder_category`: a head-noun
binder (`N`, `N_pro`, `Nom`) supplies a `Nom`; a `Coordination` binder
supplies its conjuncts' category; every other binder supplies its own
category.  On the corpus the set is `AdjP AdvP Clause NP Nom PP VP
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

### 5.1 Edges and labels

The chart is an active chart.  An **edge** is `(id, label, start, end,
needed)`, one per distinct `(label, start, end, needed)`; its score and
its best derivation (Viterbi) or inside mass are tables keyed by id
(`Chart.score`, `Chart.back`), and with `record=True` every derivation is
kept in creation order (`Chart.derivs`) for the outside pass.

`needed` says what the edge still wants:

| `needed` | span | content |
|---|---|---|
| `R` | `[start, end)`, head at `start` | the head with its right dependents so far; may take more |
| `L` | `[start, end)`, head inside | the head with all its right dependents and its left dependents so far; takes left dependents only |
| `complete` | `[start, end)` | a complete constituent |
| `conj` | `[start, end)` | a `Coordinator`-marked conjunct, waiting for its tail |
| `tail` | `[start, end)` | one or more conjuncts, the last one marked, waiting for a first conjunct on its left |

The **label** is a record, `Label(cat, gaps, binders, used, members)`,
where a field earns its place by a rule that reads it:

* `cat` is the chart category (§2.2);
* `gaps` is the sorted tuple of categories `X` still missing below the
  edge: material that a binder of category `X` has yet to supply;
* `binders` (chains only) is the sorted tuple of categories of binders
  attached on the right whose gap lies further left, not yet attached
  (a `Postnucleus` before its gap); it is always empty on a complete
  constituent;
* `used` (chains only) is the set of once-only functions attached;
* `head` (chains only) is the head's token class, which the finiteness
  and licensing rules read;
* `members` (coordinations only) is the set of the conjuncts' categories,
  a nested coordination's members flattened in: this is what the CGEL
  condition checks when the coordination fills a slot.

Both tuples are bounded by `maxgap` (2 by default).  With
`slash=False` both are always empty.

Edges are indexed by the positions they grow at, `at_start[j]` and
`at_end[j]`: each is a map from the part of the label a rule selects on
to the set of edge ids there, so that the fundamental rule is an array
lookup followed by a scan of the real candidates:

| edge | indexed under |
|---|---|
| `complete` | `(complete, D)` at both ends, `D` its table key as a dependent (`Coordination` for a coordination); and `(conjunct, gaps)` at its end, as a first or bare conjunct |
| `R` | `(R, C)` at its end, for a right dependent; `(chain, C)` at its start, for a left one |
| `L` | `(chain, C)` at its start |
| `conj` | `(conj, gaps)` at its end |
| `tail` | `(tail, gaps)` at its start |

### 5.2 Invariants

1. Every `complete`, `conj` and `tail` label has `binders == ()` and
   `used == {}`.
2. A root is a `complete` (or, outside `dependent` mode, a `conj`) edge
   over `[0, n)` with `gaps == ()` and a root-eligible category: a
   coordination needs every member rootable.
3. A binder dependent (`Prenucleus`, `Postnucleus`, `Head-Prenucleus`) is
   itself gap-free.
4. A coordination's `gaps` equals the `gaps` of each of its conjuncts
   (across the board); conjuncts share the whole gap state, so in
   `feature` mode they also share the marker feature.
5. Every surface token is used exactly once: as a head, as a bare leaf
   dependent, or as a marker consumed by MARK/conj.  (Checked by the
   tests on output trees.)
6. Every derivation's tails precede its head edge in agenda order
   (§5.4), so creation order is topological and an edge is popped only
   after every derivation of it exists.  (Checked by the tests.)
7. A head's right dependents are all attached before any left one: a
   chain is `R` until its first left dependent and `L` after.  So when a
   left binder (`Prenucleus`, `Head-Prenucleus`) is attached, every gap
   it could bind (in the head slot, on the right, or in an inner left
   dependent) is already in `gaps`, and it never waits; only a right
   binder whose gap is to its left (`Postnucleus`) can wait, in `binders`.

### 5.3 Rules

Scores are log-probabilities; `+` below is in log space.  A rule fires
when an edge is popped from the agenda, against the edges already
indexed at the position it grows at; so every pair is examined once, when
the later of the two is popped.

**Base.**  For each token `h`, every projected `C ≠ <leaf>` of its class
`L`: an `R` edge over `[h, h+1)` with `log P(C | L) + log stop_L(C) + log
stop_R(C)` and `head = L`.  For a gap token there is one base per `X ∈
gapcats` with `L = GAP/X` and `gaps = (X,)`: the gap is the head slot (an
inverted auxiliary) and the item is missing an `X`.  Marker tokens get no
base: they are never heads.

**Leaf.**  A gap token gives a `complete` edge over `[i, i+1)` with
category `GAP/X` and `gaps = (X,)` for every `X` with a leaf outcome; a
lexical token gives one with its own category when it has a `<leaf>`
outcome (name pieces).

**Attach (`attach`).**  An `R` chain and a `complete` dependent `(D,
gd)` starting at its end (a right dependent), or an `R` or `L` chain and
a `complete` dependent ending at its start (a left dependent; the result
is an `L` chain), with function `f` and emission `P(f, D | C, side)`,
subject to four structural rules, each a switch for ablation: `once` (a
head takes `Subj`, `Det`, `Obj`, `PredComp`, `Postnucleus`,
`Head-Prenucleus` at most once), `finite` (a `Subj` only on a finite
head: `V:fin`, `V_aux:fin`, `V_aux:mod`, or the inverted-auxiliary
slot), `license` (a complement function only on a head class the
treebank shows taking it), and, for a coordination dependent, every
member category licensed for `f`.  Then:

```
gaps, binders = g0 + gd, b0
if f is a binder function:
    require gd == ()                      # a binder is gap-free
    X = D.base
    if X in gaps:        remove one X from gaps   # binds a gap already present
    elif side == R and X in gapcats:
                         add X to binders         # a Postnucleus: its gap is further left
    else:                reject                   # nothing for it to bind
elif C in {NP, Nom} and D is clausal and "Nom" in gd:
    remove one "Nom" from gaps            # the head noun is the material
if binders and gd:
    cancel each pending binder against a gap of its category
require len(gaps) <= maxgap and len(binders) <= maxgap
```

The nominal rule is what binds a relative clause: the clausal dependent
is missing a nominal, and the head noun of the phrase it attaches to
supplies it.  The chain grows by the dependent's span on its side.

**Completion (`complete`).**  A chain with `binders == ()` is a
`complete` constituent over the same span, with `gaps` kept and `used`
and `head` dropped.  (The first draft built the two sides separately and
joined them at the head, cancelling pending binders of both sides there;
that let a left binder wait for a gap on its own side further out, which
the treebank never has, and it multiplied the chain states by the
pending binders of both sides.)

**MARK (`mark`).**  A `complete` edge starting at `i ≥ 1` with `ts[i-1]
== Sdr`: a `complete` edge over `[i-1, end)` with `score + log P(X |
word)`, `X` the edge's table key as a dependent; the category is kept
(`schema`) or carries the word (`feature`).  Not applied in `dependent`
mode.  Gaps and members pass through unchanged.

**conj.**  A `complete` edge starting at `i ≥ 1` with `ts[i-1] ==
Coordinator`: in `schema`/`feature` mode a `conj` edge over `[i-1, end)`
with `log P(X | word) + log(1 − p_bare)`; in `dependent` mode the marker
is already inside the constituent, which becomes the conjunct with
`log(1 − p_bare)` when it starts at a `Coordinator`.  `X` is again the
table key as a dependent, so a marked conjunct may itself be a
coordination (*and [a road between Fujairah and Dubai]*): the treebank
has two, and `Coordination` is in the coordinator's marking table.

**tail (`more`).**  A `conj` edge is a one-conjunct tail with `log(1 −
p_more)` and the conjunct's categories as members (`last`).  A tail
starting at `m` and a `conj` or a bare `complete` edge ending at `m` with
the same `gaps` make a longer tail with `log p_more` (plus `log p_bare`
for a bare conjunct), members united; a coordination may not be a bare
middle conjunct (it would duplicate the nested analysis).  Both are
subject to `coordinable`: the members must all be licensed in one and
the same slot somewhere in the grammar (CGEL's condition applied at
formation, so that coordinations no slot could take are never built).

**COORD (`coordinate`).**  A `complete` first conjunct ending at `m` and
a tail starting at `m` with the same `gaps` (across the board): a
`complete` coordination, members united and `coordinable`.  The
conjuncts need not share a category: CGEL's condition (ch. 15 §3.1) is
likeness of *function*, and it is enforced where the coordination is
attached (**Attach** above) by requiring every member category to be
licensed in the slot it fills.  A coordination at the root needs every
member rootable.  No further term is added (§9).

**Root.**  The best `complete` edge over `[0, n)` with `gaps == ()` and
base category in `ROOT_CATS`; or, outside `dependent` mode, the best such
`conj` edge (a clause-initial *and*/*but*/*so*).

### 5.4 The agenda

The agenda is a heap keyed by span size and then by `RANK`: `R` chains
before `L` chains before `complete` edges before `conj` before `tail`.
Every derivation has tails of strictly smaller span except three, all
unary: a chain completing (`R`, `L` < `complete`); a constituent becoming
a conjunct in `dependent` mode (`complete < conj`); a conjunct becoming a
one-conjunct tail (`conj < tail`).  So every derivation of an edge
exists before the edge is popped, the score of a tail is final when a
derivation is scored, and Viterbi (`max`), inside (`sum`) and outside
(the reverse of `derivs`) are three folds over the same derivation
table.

### 5.5 Ties

The features cannot tell a dependent attached to a head from the same
dependent attached inside that head's complement when both heads project
the same category: the `dep` feature names the head's category (`VP`),
not its class, and the complement's own features are unchanged by what
is attached inside it.  So *the preface was written [by Sue]* has two
Viterbi trees with exactly the same score, the PP on *was* or on
*written*, and 86 of the 218 sentences have such a tie.  The first chart
broke them by loop order; the active chart breaks them by a stated rule
(`Chart.prefer`): between two derivations of an edge with equal scores,
attach a dependent as low as possible, that is, prefer the derivation
whose dependent is the larger, so that the material goes inside the
nearer constituent (late closure, Kimball's right association).  Ties
between derivations of other rules keep the first found.  The rule is a
default where the model is silent, not a feature; the remedy is a feature
that sees the head's class (lexicalised valency), which is step 9.

### 5.6 Complexity, and the length bound

The work is cubic in `n` times the number of edge pairs examined per
position, and the labels are a product: category × open gaps (up to two,
from eight categories) × a pending `Postnucleus` × once-only state ×
coordination member sets.  Building the right side first removed the
pending binders of the left side from that product (they had multiplied
the chain states by up to 28 tuples): every sentence in the corpus now
parses, the 38-token one in 50 s and 160 MB, the 33-token one in 17 s,
the 32-token right-node-raising one in about two minutes and 440 MB.
Two structural rules keep it there rather than worse: CGEL's
coordination condition is applied when a coordination is formed, not
only when it is attached, and the never-repeated binder functions
`Postnucleus` and `Head-Prenucleus` are once-only.

The length bound `MAXTOK` is now above the corpus and stays as a switch
for the record: while the two longest sentences were infeasible (October
2026) the author chose to keep two open gaps, because the 19 heads that
need them are a real construction (wh-question with subject–auxiliary
inversion), and to exclude sentences over 32 tokens from evaluation,
reported as excluded in every summary.  The tests restrict corpus-wide
checks to sentences of at most 12 tokens.

## 6. Reconstruction (`_Rebuilder`)

### 6.1 Derivations

`Chart.back[id]` is the best derivation of an edge, a tuple naming the
rule and the tail ids:

| rule | derivation |
|---|---|
| base | `("base", L, h)` (`L` a `Cat`, `GAP/X` for a gap head; `h` the head's position) |
| leaf | `("leaf", X or None)` |
| attach | `("attach", f, side, chain id, dependent id)` |
| completion | `("done", chain id)` |
| MARK | `("mark", body id, X)` |
| COORD | `("coord", first conjunct id, tail id)` |
| conj | `("conj", body id)` or `("conj-arg", body id)` |
| tail | `("last", conjunct id)` or `("more", conjunct id, tail id)` |

`_Rebuilder.chain` walks a chain back to its base, collecting `(f, node)`
per side in surface order, and returns the base's `L` and position
(needed to pick the chain for expansion).

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
rules in either of two semirings: `max` (Viterbi, with the best
derivation kept) or `sum` (inside masses, with every derivation recorded
for an outside pass).  The weights are initialised to the log relative
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

### 9a. The active chart (done)

The chart of the first draft (five span grids of dicts, positional tuple
keys with the coordination's members and the gap category encoded in
category strings, rule-specific backpointers) was replaced by the
organisation in §5.1–5.4 in October 2026.  The acceptance test was
identity with the first draft: on every sentence of at most 20 tokens
the Viterbi score and `log Z` agree to 1e-9, except on ten sentences
where the only difference is in nested coordination, which the string
label could not state consistently: a coordinator-marked conjunct may now
itself be a coordination (two in the treebank; impossible before), and a
nested first conjunct's members are all checked against a common slot
(before, they were skipped).  Trees differ only where two derivations
tie exactly (§5.5).  The held-out numbers are in the note, §8.

The second change (the same month) built each head's right side before
its left (§5.3, invariant 7), on the author's instruction to support the
binder change whatever the cost in time.  Its comparison with the
two-sided chart exposed a fault in both earlier charts' inside pass: the
right base of a gap-headed item was entered once per gap category, so
gap-headed analyses were over-counted in `log Z` (never in Viterbi).
With that corrected in the comparison copy, the two charts agree on
`log Z` to 1e-9 on 143 of the 165 sentences of at most 20 tokens; the
rest differ by two intended changes of support: a left binder can no
longer wait for a gap on its own side further out (unattested), and the
bound of two is on the open gaps as the chain grows rather than on each
side separately.  Every sentence in the corpus now parses (§5.6).

## 10. Switches

| switch | where | default | effect |
|---|---|---|---|
| `markers` | `build_grammar` | `schema` | §3.3 |
| `maxgap` | `parse` | 2 | bound on open gaps and pending binders |
| `coord` | `parse` | `True` | COORD rule on/off |
| `slash` | `parse` | `True` | gap tuples kept/zeroed (gaps become plain tokens) |
| `once`, `finite`, `license` | `parse` | `True` | the structural rules of §5.3 **Attach** |
| `maxtok` | `evaluate` | 32 | sentences longer than this are reported as excluded, not parsed (§5.6) |
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

Fourteen tests, about 15 s: per-side normalisation and per-head projection
normalisation; markers never heads or dependents in `schema` mode; every
gap accounted for by an event or a reported skip; every parse of a short
sentence preserves its tokens and gap count; coordination output shape
(like conjuncts, marker first in the last conjunct); a subordinator sits
first in a clause or VP; every gap in every short parse is bound to a
binder of its category; filling *would this — be fine* puts *would* at
the VP head; across-the-board sharing gives one index per coordination;
a lone gap has no parse while `V_aux GAP` forces the auxiliary into
`Prenucleus`; the COORD switch; all three marker modes run and normalise;
the agenda order is topological (every tail ranks before its head and
every derivation of an edge precedes its first use); a marked conjunct
may be a coordination and members are never coordinations (fourteen
tests in all).
The linking and filling pass was also exercised on hand-built trees for
inversion, a relative clause, shared objects and two simultaneous gaps.
