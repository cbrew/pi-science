"""A minimal, standard CYK / Viterbi parser over CGEL trees.

Intent: keep this *simple and clean*, at the cost of performance, because the
corpus is tiny (220 trees) and there are no degrees of freedom to spend
tuning.  Exactly the classic pipeline:

1. **Induce a category-only PCFG** from the gold trees: for every internal
   node ``X`` with children ``b1..bk`` a rule ``X -> b1..bk`` is read off.
   (Lexical categories are the terminals; every gold leaf determines one
   surface token, so the parser works on the lexical-category yield.)
2. **Binarize deterministically.**  A k-ary rule becomes k-1 binary rules
   ``X -> b1 X|1;  X|1 -> b2 X|2; ...;  X|k-2 -> b_{k-1} bk``, where ``X|i``
   is the unique auxiliary "the remaining children of X after the i-th".
   The full production probability rides on the first binary rule; the
   factor rules carry 1.  Deterministic: parent + index, nothing else.
3. **One smoothing constant (add-one, lmb=1)** on the production rules.
4. **Transitive unary closure** for the projection chains (Clause->VP,
   NP->Nom, ...).
5. **Classic CYK + Viterbi** over spans, with a unary-close pass on every
   cell; the best tree is recovered by standard backtracking (aux nodes
   collapsed back into the original k-ary parent).

Validation is honest and low-effort: a 5-fold cross-validation (fixed seed)
reporting coverage, labeled bracketing F1, exact-match and root-match, plus a
self-fit upper bound.  Expect the numbers to be modest: 220 training trees is
simply not much grammar to learn.

Run:  python3 cgel_cyk.py --eval
      python3 cgel_cyk.py --demo
"""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cgel_reader import Node, Sentence, parse_cgel_file

CGEL = Path(__file__).resolve().parent / "cgel"
LOG0 = -math.inf
ROOT_CATS = {"Clause", "Coordination", "NP", "VP", "Nom", "AdjP"}


# ---------------------------------------------------------------------------
# grammar induction
# ---------------------------------------------------------------------------

def collect_rules(sentences: Iterable[Sentence]) -> Counter:
    rules: Counter = Counter()
    for s in sentences:
        for n in s.root.iter_nodes():
            if n.children:
                rules[(n.cat, tuple(c.cat for c in n.children))] += 1
    return rules


class Grammar:
    """Category-only PCFG, deterministically binarized, add-one smoothed."""

    def __init__(self, rules: Counter, lmb: float = 1.0):
        self.lmb = lmb
        self.terminals = set()                 # preterminals: leaf categories
        self.unary: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self.binary: Dict[Tuple[str, object], List[Tuple[str, float]]] = \
            defaultdict(list)
        # left-child -> {right-child -> [(A, p)]}   (fast CYK lookup)
        self.bin_by_B = defaultdict(lambda: defaultdict(list))
        byA: Dict[str, List[Tuple[tuple, int]]] = defaultdict(list)
        # collect rules per LHS
        per: Dict[str, Dict[tuple, int]] = defaultdict(Counter)
        for (A, rhs), c in rules.items():
            per[A][rhs] += c
            for b in rhs:
                self.terminals.add(b)
        for A, rhs_counts in per.items():
            tot = sum(rhs_counts.values())
            V = len(rhs_counts)
            for rhs, c in rhs_counts.items():
                p = (c + lmb) / (tot + lmb * (V + 1))
                self._add_rule(A, rhs, p)
        self._unary_closure()

    def _add_rule(self, A: str, rhs: tuple, p: float) -> None:
        k = len(rhs)
        if k == 1:
            self.unary[A].append((rhs[0], p))
            return
        # binarize: A -> b1 A|1 ; A|k-2 -> b_{k-1} b_k  (aux = (A, i))
        prev = A
        for i in range(k - 1):
            b = rhs[i]
            nxt: object = rhs[i + 1] if i == k - 2 else (A, i + 1)
            self.binary[(b, nxt)].append((prev, p if i == 0 else 1.0))
            self.bin_by_B[b][nxt].append((prev, p if i == 0 else 1.0))
            prev = nxt

    def _unary_closure(self) -> None:
        # best forward path A ->* B
        self._fwd_map: Dict[Tuple[str, str], float] = {}
        for A in self.unary:
            dist = {A: 0.0}
            changed = True
            while changed:
                changed = False
                for X, dx in list(dist.items()):
                    for B, p in self.unary.get(X, ()):
                        if dx + math.log(p) > dist.get(B, LOG0):
                            dist[B] = dx + math.log(p)
                            changed = True
            for B, lp in dist.items():
                if B != A:
                    self._fwd_map[(A, B)] = lp
        self._rev: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        for (A, B), lp in self._fwd_map.items():
            self._rev[B].append((A, lp))

    def u_best(self, a: str, b: str) -> Optional[float]:
        """Best unary-path log-prob a ->* b, or None."""
        return self._fwd_map.get((a, b))

    def unary_close(self, cell: Dict[str, float]) -> Dict[str, float]:
        """Add every parent reachable by unary rules from a present category."""
        out = dict(cell)
        for A, lpA in cell.items():
            for P, ulp in self._rev.get(A, ()):
                v = lpA + ulp
                if v > out.get(P, LOG0):
                    out[P] = v
        return out


# ---------------------------------------------------------------------------
# CYK + Viterbi
# ---------------------------------------------------------------------------

class Parse:
    def __init__(self, tree: Node, logp: float, brackets: set, root_cat: str):
        self.tree = tree
        self.logp = logp
        self.brackets = brackets
        self.root_cat = root_cat


def parse(gram: Grammar, tokens: Sequence[str]) -> Optional[Parse]:
    n = len(tokens)
    if n == 0:
        return None
    chart = [[{} for _ in range(n + 1)] for _ in range(n)]
    back = [[{} for _ in range(n + 1)] for _ in range(n)]

    def setbest(i, j, cat, lp, bl, br):
        old = back[i][j].get(cat)
        if old is None or lp > old[0]:
            back[i][j][cat] = (lp, bl, br)
            chart[i][j][cat] = lp

    for i in range(n):                              # base: one token each
        chart[i][i + 1][tokens[i]] = 0.0
        back[i][i + 1][tokens[i]] = (0.0, None, None)
        chart[i][i + 1] = gram.unary_close(chart[i][i + 1])

    for L in range(2, n + 1):                       # combine shorter spans
        for i in range(0, n - L + 1):
            k = i + L
            for j in range(i + 1, k):
                left, right = chart[i][j], chart[j][k]
                if not left or not right:
                    continue
                for B, lbp in left.items():
                    prow = gram.bin_by_B.get(B)
                    if not prow:
                        continue
                    for C, rbp in right.items():
                        rec = prow.get(C)
                        if not rec:
                            continue
                        for (A, p) in rec:
                            setbest(i, k, A, lbp + rbp + p, (i, j), (j, k))
            chart[i][k] = gram.unary_close(chart[i][k])

    root_cell = chart[0][n]
    if not root_cell:
        return None
    root_cat, rlp = max(((c, lp) for c, lp in root_cell.items() if c in ROOT_CATS),
                        default=(None, LOG0))
    if root_cat is None:
        root_cat, rlp = max(root_cell.items(), key=lambda kv: kv[1])
    tree = _build_node(gram, back, tokens, 0, n, root_cat)
    return Parse(tree, rlp, _brackets(tree), root_cat)


def _best_cat(back, i, j):
    return max(back[i][j], key=lambda c: back[i][j][c][0])


def _build_node(gram, back, tokens, i, j, cat) -> Node:
    """Rebuild a real category node, collapsing the binarization chain."""
    lp, bl, br = back[i][j][cat]
    if bl is None:
        if i + 1 == j and tokens[i] == cat:         # the token itself
            return Node(cat=cat, feats={"t": [cat]})
        kid = _unary_child(gram, back, i, j, cat)   # unary projection
        child = _build_node(gram, back, tokens, i, j, kid)
        child.edge = "Head"
        return Node(cat=cat, children=[child])
    # binary: A -> b1 X|1 ...; collect the real children b1..bk
    ci, cj = bl
    children = [_build_node(gram, back, tokens, ci, cj, _best_cat(back, ci, cj))]
    ci, cj = br
    ccat = _best_cat(back, ci, cj)
    while isinstance(ccat, tuple):                  # an auxiliary (A, i)
        clp, cbl, cbr = back[ci][cj][ccat]
        if cbl is None:                             # should not happen for aux
            break
        cli, clj = cbl
        children.append(_build_node(gram, back, tokens, cli, clj,
                                    _best_cat(back, cli, clj)))
        ci, cj = cbr
        ccat = _best_cat(back, ci, cj)
    children.append(_build_node(gram, back, tokens, ci, cj, ccat))
    return Node(cat=cat, children=children)


def _unary_child(gram, back, i, j, cat):
    best_kid, best_v = None, LOG0
    for kid, (klp, _, _) in back[i][j].items():
        ulp = gram.u_best(cat, kid)
        if ulp is not None and klp + ulp > best_v:
            best_v, best_kid = klp + ulp, kid
    return best_kid if best_kid is not None else _best_cat(back, i, j)


def _brackets(root: Node) -> set:
    """Labelled bracketing {(cat, (i,j))} over realized (non-gap) tokens."""
    leaves = [n for n in root.iter_nodes() if n.is_lexical]
    idx = {id(n): i for i, n in enumerate(leaves)}
    out = set()

    def walk(n):
        if n.is_lexical or n.is_gap:
            return (idx[id(n)], idx[id(n)] + 1) if n.is_lexical else None
        lo, hi = None, None
        for c in n.children:
            sp = walk(c)
            if sp and sp[0] is not None:
                lo = sp[0] if lo is None else min(lo, sp[0])
                hi = max(hi if hi is not None else 0, sp[1])
        if lo is not None and (hi - lo) > 0 and not n.is_gap:
            out.add((n.cat, (lo, hi)))
        return (lo, hi)
    walk(root)
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def sentence_tokens(s: Sentence) -> List[str]:
    return [n.cat for n in s.root.iter_nodes() if n.is_lexical]


def evo_metrics(pred: set, gold: set):
    if not gold:
        return (1.0, 1.0, 1.0, pred == gold)
    inter = len(pred & gold)
    p = inter / len(pred) if pred else 1.0
    r = inter / len(gold)
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f, pred == gold)


def evaluate(sentences: List[Sentence], gram: Grammar) -> List[tuple]:
    rows = []
    for s in sentences:
        gold = _brackets(s.root)
        pr = parse(gram, sentence_tokens(s))
        if pr is None:
            rows.append((s.sent_id, 0.0, 0.0, 0.0, False, False, False))
            continue
        p, r, f, exact = evo_metrics(pr.brackets, gold)
        rows.append((s.sent_id, p, r, f, exact, pr.root_cat == s.root.cat, True))
    return rows


def _mean(xs):
    return statistics.mean(xs) if xs else 0.0


def cross_validate(sentences: List[Sentence], folds: int = 5, seed: int = 0,
                   lmb: float = 1.0) -> None:
    rng = random.Random(seed)
    order = list(sentences)
    rng.shuffle(order)
    size = (len(order) + folds - 1) // folds
    f1s, exacts, roots, parsed = [], 0, 0, 0
    for fold in range(folds):
        test = order[fold * size:(fold + 1) * size]
        train = [s for s in order if s not in test]
        gram = Grammar(collect_rules(train), lmb=lmb)
        for row in evaluate(test, gram):
            if not row[6]:
                continue
            parsed += 1
            f1s.append(row[3])
            exacts += row[4]
            roots += row[5]
    total = len(sentences)
    print(f"5-fold CV (add-one lmb={lmb:g}): parsed={parsed}/{total}  "
          f"F1={_mean(f1s):.3f}  exact={exacts}  root-match={roots}/{parsed}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--demo", metavar="SUBSTR", default="")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lmb", type=float, default=1.0)
    args = ap.parse_args()

    sentences = [s for f in sorted(CGEL.glob("*.cgel"))
                 for s in parse_cgel_file(str(f))]
    if args.eval:
        self_rows = evaluate(sentences, Grammar(collect_rules(sentences),
                                                lmb=args.lmb))
        f = [r[3] for r in self_rows if r[6]]
        print(f"self-fit upper bound: parsed={sum(1 for r in self_rows if r[6])}/"
              f"{len(sentences)}  F1={_mean(f):.3f}  "
              f"exact={sum(1 for r in self_rows if r[4])}")
        cross_validate(sentences, folds=args.folds, lmb=args.lmb)

    if args.demo:
        gram = Grammar(collect_rules(sentences), lmb=args.lmb)
        for s in sentences:
            if args.demo and args.demo not in s.sent:
                continue
            tokens_ = sentence_tokens(s)
            pr = parse(gram, tokens_)
            print("\nsent:", s.sent)
            print("yield:", " ".join(tokens_))
            if pr is None:
                print("  (no parse)")
            else:
                print(f"  root={pr.root_cat}  logp={pr.logp:.3f}")
                print("  " + _render(pr.tree))
            if args.demo:
                break


def _render(n: Node, depth: int = 0) -> str:
    if n.is_lexical:
        return f"({n.cat} {n.surface or ''})"
    inner = " ".join(_render(c, depth + 1) for c in n.children)
    return f"({n.cat} {inner})"


if __name__ == "__main__":
    main()
