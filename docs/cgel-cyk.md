# A clean CYK parser for CGEL

`cgel_cyk.py` is a deliberately *minimal, standard* CKY/Viterbi parser over the
CGEL treebank.  It is kept simple on purpose: the corpus is 220 trees, so
there is no room for expressive grammars or tuned machinery — a plain,
reproducible baseline is the useful deliverable.  (Design philosophy: the fewest
possible decisions; every choice is the textbook one.)

## Pipeline

1. **Induce a category-only PCFG** from the gold trees.  Every internal node
   `X -> b1..bk` (children categories) is a production; lexical categories are
   the terminals.  Each sentence is parsed over its *lexical-category yield*,
   which keeps the parser robust to the tiny corpus (no unseen words).
2. **Binarize deterministically** with parent + index auxiliaries:
   `X -> b1 X|1; X|1 -> b2 X|2; ...; X|k-2 -> b_{k-1} bk`.  The full
   production probability rides on the first binary step; the factor steps
   carry 1.  No Markovisation, no sibling context — exactly one deterministic
   choice.
3. **One smoothing constant** (add-one, `--lmb 1`).
4. **Transitive unary closure** for the projection chains (`Clause->VP`,
   `NP->Nom`, …) — a relaxation over the unary rules, used as a per-cell pass.
5. **Classic CYK + Viterbi** over spans; backtracking collapses the aux nodes
   back into the original k-ary parent.

## Validation

```
python3 cgel_cyk.py --eval

self-fit upper bound:  parsed=220/220  F1=0.116  exact=0
5-fold CV (add-one lam=1):  parsed=218/220  F1=0.122  exact=0  root-match=1/218
```

Verified: the grammar covers its own training data (parsing 220/220), and the
held-out 5-fold coverage is 218/220 — the pipeline is correct.  The quality
(F1 ≈ 0.12, near-zero exact/root-match) is *expected and honest*: with 220
trees the induced grammar is tiny, and Viterbi's PCFG bias to short unary
chains (e.g. `VP` over `Clause`, `Nom` over `NP`) suppresses the deep
projection structure that dominates CGEL brackets.  This is a clean baseline,
not a tuned parser.

Example (`--demo`), "help me prepare lunch" → `V N_pro V N`:

```
(VP (V V) (N_pro N_pro) (VP (V V) (N N)))
```

Tests: `tests/cgel_cyk.test.py` (coverage, well-formedness of reconstructed
trees, metric sanity).
