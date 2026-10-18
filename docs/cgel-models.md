# Probability models over CGEL treebank analyses

`cgel_models.py` defines two families of probability models over the labelled
analyses of a sentence, built on the conventions documented in
[`cgel-conventions.md`](cgel-conventions.md) (head rule, X-bar projection
skeleton, function-parent / function-child licensing) and the reader in
`cgel_reader.py`.

Both questions are answered, in two model families:

| family | space | structure in the model? |
|---|---|---|
| **Model A / Model B** (`ModelA`, `ModelB`) | label assignments to an *attested* skeleton | no (shape fixed from corpus) |
| **Structural A / B** (`StructuredModel`, `--structured`) | whole trees (shape **and** labels), generated | yes |

The two-model contrast is the same in both families: **A** treats labels as
independent draws; **B** is the same feature family with support restricted to
analyses that follow the discovered conventions (everything else has
probability exactly 0).

---

## 1. Skeleton-conditional models  (Model A vs Model B)

For every sentence the *shape* of the tree is the attested one (its skeleton:
the structural nodes, with words and GAP indices held fixed at their leaves).
A *labelling* is an assignment of a `(category, function)` pair to every
variable node. (Category and function labels are correlated in the annotation;
in these models they are two separate labels, as requested. The root's
incoming function is structural — the sentinel `ROOT` — and is not part of the
label space.)

### Model A — labels independent

Each variable node independently draws its category (`P_cat`) and its incoming
function (`P_edge`); both are multinomials fit by MLE with Laplace smoothing
(`alpha=1.0`, over the 220 sentences).  The probability of a labelling is

    P_A(labelling) = prod_nodes P_cat(cat) * prod_nodes P_edge(edge)

which is a proper (trivially normalised, Z_A = 1) distribution.  A assigns
positive probability to analyses that contradict the grammar of the treebank,
e.g. an `N` directly under `Clause :Subj`.

### Model B — a log-linear model restricted to the conventions

The same per-node category and edge features, scored with log-weights, but the
sum in the normaliser runs *only over labelings that satisfy the conventions*:

    P_B(labelling) = exp( sum_weight_cat + sum_weight_edge ) / Z_B
    Z_B = sum over conforming labelings of exp( ... )

where a labelling conforms iff every adjacent pair `(parent_cat, edge,
child_cat)` is licensed by `cgel_grammar.allowed` (head rule, X-bar,
function-parent/function-child).  Non-conforming labelings get probability 0.

Because the constraints are local to adjacent nodes, the partition function,
per-node marginals, sampling and Viterbi MAP decoding are computed **exactly
by dynamic programming** on the skeleton:

* `up_messages`  — bottom-up log-masses per `(slot, parent_cat)`; gives `log Z_B`;
* `marginals`    — top-down pass; per-node `P(cat)` / `P(edge)` (used for
  feature expectations in `fit_loglinear`);
* `sample`       — exact forward-filtering / back-sampling;
* `argmax`       — Viterbi with a memoised `(slot, parent_cat)` table and
  backtracking from the root (a per-node store would be overwritten by
  non-MAP parent categories).

Two weight sets are provided for B:

* **restricted B**: the *probabilities* of A are used as the weights and the
  normaliser re-restricts to the conforming support;
* **fitted B** (`--fit-b`, `fit_loglinear`): maximum-likelihood training of
  the log-weights by Adam-lite gradient ascent, gradient
  `dL/dw = E[f] - f(attested)` with the expectation from the exact DP
  (the indicator features on which analyses with different shapes differ
  cancel; this family conditions on the skeleton, so it can only re-weight
  labels).

### Consequences

* `Z_B = P_A(conforming)` exactly (since Z_A = 1): the median of `Z_B` over
  the 220 sentences is the probability that a random skeleton labelling drawn
  from A is grammatical.  It is astronomically small
  (the *restriction cost*, `log Z_B` ≈ 60 nats per tree), and the same value
  is obtained by direct Monte Carlo sampling of A (`--eval` prints both).
* On the attested analyses B always scores far higher than A
  (avg log gain ≈ +60), since the attested trees conform and B concentrates
  all mass on the conforming subset.

## 2. Structural (generative) models  (`--structured`)

Skeleton-conditional models score the *labelling* but not the *shape*: every
sentence contributes its tree shape for free.  The structural models generate
the whole tree — branching (shape) and labels — as a single-type branching
process:

1. the root category is drawn from `p_root` (over the observed root cats);
2. every node draws its **degree** (number of children) from the corpus's
   degree distribution `p_deg` (mean arity µ ≈ 0.98, sub-critical: a proper
   distribution over finite trees, expected size ≈ 1/(1−µ) ≈ 42, matching the
   corpus mean); leaves are the nodes that draw degree 0;
3. each child is drawn as an `(edge, category)` pair:
   * **Model A**: independently from `p_cat × p_edge`;
   * **Model B**: from `p_cat × p_edge` renormalised over the *licensed*
     child cells of that parent — so B can never produce a
     convention-violating tree while A can.

The probability of a full tree is

    P(tree) = p_root(root) * prod_nodes p_deg(deg) * prod_edges pick(parent, edge, child)

and includes the *structural* terms (every node's degree) alongside the label
terms.

**Normalisation.** B's licensed-only child draws shift probability mass onto
phrase children, pushing the unrestricted branching process supercritical
(no distribution over all finite trees exists).  Both models are therefore
normalised **exactly over the space of trees of depth ≤ D** (D = the deepest
tree in the corpus, 25), which is finite for both models.  The partition
`log Z` and the expected tree size are computed exactly by depth iteration:

    T_d(c) = sum_k p_deg(k) * ( child_mass_d-1(c) )^k ,   T_-1 = 0
    log Z  = logsum_c p_root(c) * T_D(c)

`logp(tree) = tree weight − log Z`, and the expected node count follows the
same recursion (linear space).

### What the numbers show

```
mean arity mu          0.98     (sub-critical)
expected tree size     A: 20   B: 10   (depth-bounded; corpus mean 42.5)
log Z                  A: -0.06  B: -0.28
avg log p(attested)    A: -230  B: -154
P_A(conforming)        ~ 0.44
```

* A is sub-critical: its partition is ≈ 1 (`log Z_A ≈ 0`), the generating
  process check.
* B scores the attested trees higher (+76 nats avg), even though it supports
  fewer trees: the convention restriction buys far more than it costs because
  **every attested tree actually conforms**.
* `P_A(conforming) ≈ 0.44`: under the independent-tree generator about 44% of
  random trees happen to be licensed — vastly higher than under the
  skeleton-conditional A (where a random *labelling* of a real skeleton
  conforms only ~10⁻²⁶ of the time), because the structural model already
  generates plausible branching, and the conventions mostly constrain the
  labels that ride on it.

## 3. Files and interfaces

| symbol | purpose |
|---|---|
| `ModelA.fit`, `logp`, `sample` | independent-label model (Z = 1) |
| `ModelB(weight_cat, weight_edge)`, `up_messages`, `marginals`, `sample`, `argmax`, `logp` | exact-DP convention-restricted model |
| `fit_loglinear(...)` | MLE of Model B's log-weights |
| `fit_structured(...)` | generative models (shape + labels), modes A / B |
| `StructuredModel.logp / sample / conforms / _partitions` | depth-bounded generative scoring, sampling, conformance |
| `evaluate` / `evaluate_structured` | per-sentence likelihoods, Z_B, Monte Carlo conformity |

Tests: `tests/cgel_models.test.py` (16 tests: exactness of the DP vs brute
force on a toy tree; normalisation of marginals; Viterbi backtracking
correctness; support restriction; sampling conformance; fitting improves the
likelihood; structural-generative checks).  All suites run in under a second.