# Bottom-up, head-driven generative models (Eisner split-head)

`cgel_splithead.py` explores whether we can build *better* generative models
for the CGEL treebank **from the bottom up**, using Eisner's **split-head**
model (Eisner, *An empirical comparison of probability models for dependency
grammar*, 1996) to generate productions, and anchoring every phrase on the
**parts of speech / words** it contains.

The headline result: **the normalisation problem that Model B hit in
`cgel-models.md` does not arise here**, exactly as hypothesised.  In Model B a
node drew an *unbounded* number of children, so the renormalised-to-licensed
child picks could push the branching process supercritical and forced an
artificial depth bound.  In the split-head model each head's dependents form a
**left sequence and a right sequence, each explicitly terminated by STOP**, so
every local process is a proper (stopped-renewal) distribution and the total
mass is 1 at every node — verified to 9 decimal places on the corpus.

## The generative story (bottom up)

Every CGEL constituent has a **single lexical head** (the head rule in
`docs/cgel-conventions.md`; 5,566 Head edges, 0 violations, and empirically
**no node has more than one head**).  The head's *dependents* are its
non-head children.  For each head/projection `C` with head word of category
`POS`:

1. **project**: `P(C | POS)` — how a word of a given part of speech projects
   (the X-bar/projection convention, quantified).  Sharp and clean:
   `Nom←N, NP←N, VP←V, PP←P, Clause←V, DP←D, …`.
2. **split**: on each side, generate a *stopped sequence* of dependents
   `(function, dependent-category)`:

       P_L(left)   = p_stop(C,L) · Π p_dep((f,D) | C,L)
       P_R(right)  = p_stop(C,R) · Π p_dep((f,D) | C,R)
       p_stop(C,S) + Σ_{f,D} p_dep((f,D) | C,S)  =  1

3. **recurse**: each dependent is itself a phrase with its own head, so the
   process repeats — but always anchored inside the **finite observed word
   string**, so it terminates.

Because

    Σ over all left-sequences of P_L  =  p_stop · Σ_k (Σ p_dep)^k  =  1,

every head contributes a properly normalised distribution and the whole
analysis is a proper distribution over the (finite) set of analyses of the
observed string — **no partition function `Z`, no depth bound, no
supercritical branching**.  `check_normalization()` confirms
`p_stop + Σ p_dep = 1.0000` and total sequence mass `1.0000` for **every**
category/side, and the expected number of dependents `E[#deps] = Σp_dep/p_stop`
is small and finite everywhere (0.0–1.0).

## What the corpus teaches the model

Directionality comes out sharp and grammatical (strongest per side):

| head | side | argument | E[# this kind] | note |
|---|---|---|---|---|
| Clause | left | Subj : NP | 0.45 | subject before head |
| NP | left | Det : DP | 0.28 | determiner before head |
| PP | right | Obj : NP | 0.63 | preposition's complement |
| VP | right | Comp : Clause | 0.30 | clausal complement |
| VP | right | Obj : NP | 0.24 | object |
| AdjP | left | Mod : AdvP | 0.12 | degree modifier |

So verbs project clauses and take complements to the right, nouns take
determiners to the left and complement/relative to the right, prepositions
take their object to the right — all learned from 220 trees.

## Per-analysis likelihood

The model assigns to each attested analysis a well-defined, finite
probability.  On the corpus:

```
avg log P(tree)             ≈ -73.6 per sentence
avg log P per surface token ≈ -4.76
```

These are genuine *conditional* (given-the-words) probabilities with no
normalisation constant, so they are much more interpretable than the
skeleton-conditional or structural numbers in `cgel-models.md` (which live in
different probability spaces and needed a depth bound).  The split-head model
is the only one of the four we've built that is simultaneously (a) fully
normalised, (b) generative from words/POS, and (c) free of any partition /
depth-bound machinery.

## Coverage & the flat fallback

5,087 projections (87%) decompose cleanly into a single head plus left/right
dependents.  741 nodes (13%) are **flat** — coordination, GAP/displaced
elements, and ambiguous spans — and are handled by a coarser single stopped
sequence over the whole child list (also normalised).  A genuine web of the
tree's structure, including auxiliary inversion (fronted `Head-Prenucleus` in
wh-relative clauses like "*what* we are trying to do …"), correctly falls to
the flat/left-dependent handling.

## Example

"help me prepare lunch" (bottom-up):

```
Clause  head:<V 'help'>                      left:-            right:-
  VP    head:<V 'help'>                      left:-            right: Obj:NP | Comp:Clause
    NP   ...me...                            (pronoun head, projects Nom→NP)
    Clause head:<V 'prepare'>                left:-            right:-
      VP  head:<V 'prepare'>                 left:-            right: Obj:NP
        NP  ...lunch...                      (N head, projects Nom→NP)
```

## Files

| symbol | what |
|---|---|
| `iter_events(sentence)` | decompose a tree into head-driven / flat events |
| `_dominant_child` / `_head_leaf` | head-rule driven head path to the lexical head word |
| `SplitHead.fit` | MLE + smoothing of `p_proj`, `p_dep`, `p_stop`, flat tables |
| `SplitHead.loglik` | exact per-analysis log-probability (no Z) |
| `SplitHead.check_normalization` | verifies `p_stop + Σ p_dep = 1` and total sequence mass 1 per side |
| `worked_example` | render a sentence's bottom-up head→argument derivation |

Tests: `tests/cgel_splithead.test.py` (7 tests, ~0.03 s).

A full CKY-style parser (searching the space of analyses of a string rather
than scoring the attested one) is the natural next step; the extraction here
is the equivalent generative model it would optimise.
