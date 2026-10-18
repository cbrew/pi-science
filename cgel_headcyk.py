"""Head-driven (Eisner/Collins-style) parser for CGEL, built out from heads.

Replaces the MLE-production PCFG baseline (`cgel_cyk.py`) with the generative
story we already fit in `cgel_splithead.py` -- each head builds its phrase by
taking a **stopped left sequence and a stopped right sequence of arguments**:

    P(phrase C | head word of lexical category L)
        = P(C | L)                    # the head projects (head rule / X-bar)
        * [stop_L(C) * prod over left  args  emit_L(argcat | C)]
        * [stop_R(C) * prod over right args  emit_R(argcat | C)]

Emissions are aggregated from the split-head tables over grammatical functions
(`emit(cat|C) = sum_f p_dep(f,cat | C,side)`), so the per-side sequences are
properly normalised (`stop + sum emit = 1`) -- no partition function, no depth
bound, no supercritical branching.

Parsing is the **Eisner-style head-outward dynamic program** with three
structures over spans:

  * `left[h][h]  = P(C|L_h) + stop_L(C)`              -- the head token alone
  * `left[i][h]  = max over an arg over [i,m) and D of`
                        `arg[i][m][D] + emit_L(D|C) + left[m][h][C]`
  * `right[h][k] = max over an arg over [h+1,m) and D of`
                        `arg[h+1][m][D] + emit_R(D|C) + right[m][k][C]`
  * `arg[i][k][C] = max over head h of left[i][h][C] + right[h][k][C]`

Because each constituent's head is one boundary token and its arguments are
complete constituents, every surface token is used exactly once as a head --
there is no "two heads in one constituent" divergence problem.  Unary
projection chains are folded into the single head projection `P(C|L)` (a
documented simplification: intermediate unary nodes are not in the produced
tree).  Viterbi decoding records backpointers and reconstructs the tree, with
the head leaf placed between the left and right argument sequences.

Validation mirrors `cgel_cyk.py`: self-fit and 5-fold CV reporting coverage,
labelled-bracket F1, exact-match and root-match.  No tuning: one smoothing
constant (alpha=1.0) on the split-head tables.

Run:    python3 cgel_headcyk.py --eval
        python3 cgel_headcyk.py --demo
"""
from __future__ import annotations

import math
import random
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cgel_reader import Node, Sentence, parse_cgel_file
from cgel_splithead import SplitHead, iter_events

CGEL = Path(__file__).resolve().parent / "cgel"
LOG0 = -math.inf
ROOT_CATS = {"Clause", "Coordination", "NP", "VP", "Nom", "AdjP"}


# ---------------------------------------------------------------------------
# grammar tables (from the split-head fit, aggregated over functions)
# ---------------------------------------------------------------------------

class HeadGrammar:
    def __init__(self, model: SplitHead):
        cats = set()
        for (L, C) in model.anchor:
            cats.add(C)
        for (cat, side, (f, d)) in model.dep:
            cats.add(d)
        # projection prior: P(C | L)
        self.proj: Dict[Tuple[str, str], float] = dict(model.anchor)
        # per-side argument emission, aggregated over function labels
        self.emitL: Dict[Tuple[str, str], float] = {}
        self.emitR: Dict[Tuple[str, str], float] = {}
        for (cat, side, (f, d)), p in model.dep.items():
            t = self.emitL if side == "L" else self.emitR
            t[(cat, d)] = t.get((cat, d), 0.0) + p
        self.stopL: Dict[str, float] = {c: p for (c, s), p in model.stop.items() if s == "L"}
        self.stopR: Dict[str, float] = {c: p for (c, s), p in model.stop.items() if s == "R"}
        self.cats = sorted(cats)


class Parse:
    def __init__(self, tree: Node, logp: float, brackets: set, root_cat: str):
        self.tree, self.logp, self.brackets, self.root_cat = \
            tree, logp, brackets, root_cat


def build_grammar(sentences, alpha: float = 1.0) -> HeadGrammar:
    model = SplitHead.fit(sentences, alpha=alpha)
    return HeadGrammar(model)


# ---------------------------------------------------------------------------
# head-outward (Eisner-style) Viterbi
# ---------------------------------------------------------------------------

def parse(hg: HeadGrammar, lst: Sequence[str],
          words: Optional[Sequence[str]] = None) -> Optional[Parse]:
    """Head-outward (Eisner-style) Viterbi over the lexical-category
    sequence.  Three tables, each scored in log space and carrying a
    backpointer, keyed by footprint F = number of token slots:
      left[i][h][C]  head at h, left args over [i,h);  base (i==h) =
                     proj(C|L_h),stop_L   (projection counted once, here)
      right[h][k][C] right args over [h+1,k), no projection; base (k==h+1)
                     = stop_R
      arg[i][k][C]   complete constituent over [i,k) =
                     max_h left[i][h] + right[h][k]
    Loop F ascending: arg(F) uses only <F left/right; left(F) and right(F)
    use arg(F) and strictly smaller cells -- so every dependency is already
    computed.
    """
    ts = list(lst)
    n = len(ts)
    if n == 0:
        return None
    words = list(words) if words else [None] * n
    CATS = hg.cats
    left = [[{} for _ in range(n + 1)] for _ in range(n + 1)]
    right = [[{} for _ in range(n + 1)] for _ in range(n + 1)]
    arg = [[{} for _ in range(n + 1)] for _ in range(n + 1)]

    for F in range(0, n + 1):
        # ------ arg cells with span [i, i+F) -----------------------------
        if F >= 1:
            for i in range(0, n - F + 1):
                k = i + F
                for C in CATS:
                    best, bh = LOG0, None
                    for h in range(i, k):
                        lv = left[i][h].get(C)
                        rv = right[h][k].get(C)
                        if lv is None or rv is None:
                            continue
                        v = lv[0] + rv[0]
                        if v > best:
                            best, bh = v, h
                    if bh is not None:
                        arg[i][k][C] = (best, bh)
        # ------ left cells: head at h=i+F, left args over [i,h) ----------
        for i in range(0, n - F):
            h = i + F
            if F == 0:
                for C in CATS:
                    pp = hg.proj.get((ts[h], C))
                    sl = hg.stopL.get(C)
                    if pp and sl:
                        left[h][h][C] = (math.log(pp) + math.log(sl), "base")
                continue
            for C in CATS:
                best, bk = LOG0, None
                for m in range(i + 1, h + 1):
                    ac = arg[i][m]
                    tail = left[m][h].get(C)
                    if not ac or tail is None:
                        continue
                    for D, (asc, _) in ac.items():
                        e = hg.emitL.get((C, D))
                        if e is None or e == 0:
                            continue
                        v = asc + math.log(e) + tail[0]
                        if v > best:
                            best, bk = v, (m, D)
                if bk is not None:
                    left[i][h][C] = (best, bk)
        # ------ right cells: head at h, right args over [h+1, k=h+F+1) --
        for h in range(0, n - F):
            k = h + F + 1
            if F == 0:
                for C in CATS:
                    sr = hg.stopR.get(C)
                    if sr:
                        right[h][h + 1][C] = (math.log(sr), "stop")
                continue
            for C in CATS:
                best, bk = LOG0, None
                # outermost (rightmost) arg over [m,k), inner over [h+1,m)
                for m in range(h + 1, k + 1):
                    src = arg[m][k]
                    tail = right[h][m].get(C)
                    if not src or tail is None:
                        continue
                    for D, (asc, _) in src.items():
                        e = hg.emitR.get((C, D))
                        if e is None or e == 0:
                            continue
                        v = asc + math.log(e) + tail[0]
                        if v > best:
                            best, bk = v, (m, D)
                if bk is not None:
                    right[h][k][C] = (best, bk)

    root_cell = arg[0][n]
    root_cat, rlp = max(((C, sc) for C, (sc, _) in root_cell.items()
                         if C in ROOT_CATS), default=(None, LOG0))
    if root_cat is None:
        return None
    tree = _make_rebuilder(ts, words, left, right, arg)(0, n, root_cat)
    return Parse(tree, rlp, _brackets(tree), root_cat)


def _make_rebuilder(ts, words, left, right, arg):
    """Closure-based reconstruction of the head-outward parse."""
    def complete(i, k, C) -> Node:
        score, bh = arg[i][k][C]
        head = Node(cat=ts[bh], feats={"t": [words[bh] or ts[bh]]})
        return Node(cat=C, children=_left(i, bh, C) + [head] + _right(bh, k, C))
    def _left(i, h, C):
        if i == h:
            return []
        _, bk = left[i][h][C]
        m, D = bk
        return [complete(i, m, D)] + _left(m, h, C)
    def _right(h, k, C):
        if h + 1 > k:
            return []
        rec = right[h][k].get(C)
        if rec is None or rec[1] == "stop":
            return []
        _, (m, D) = rec
        return _right(h, m, C) + [complete(m, k, D)]
    return complete


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _brackets(root: Node) -> set:
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


def sentence_tokens(s: Sentence):
    return [n.cat for n in s.root.iter_nodes() if n.is_lexical]


def sentence_words(s: Sentence):
    return [n.surface or "" for n in s.root.iter_nodes() if n.is_lexical]


def evo_metrics(pred: set, gold: set):
    if not gold:
        return (1.0, 1.0, 1.0, pred == gold)
    inter = len(pred & gold)
    p = inter / len(pred) if pred else 1.0
    r = inter / len(gold)
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f, pred == gold)


def evaluate(sentences, hg):
    rows = []
    for s in sentences:
        gold = _brackets(s.root)
        pr = parse(hg, sentence_tokens(s), sentence_words(s))
        if pr is None:
            rows.append((s.sent_id, 0.0, 0.0, 0.0, False, False, False))
            continue
        p, r, f, exact = evo_metrics(pr.brackets, gold)
        rows.append((s.sent_id, p, r, f, exact, pr.root_cat == s.root.cat, True))
    return rows


def _mean(xs):
    return statistics.mean(xs) if xs else 0.0


def cross_validate(sentences, folds: int = 5, seed: int = 0, alpha: float = 1.0):
    rng = random.Random(seed)
    order = list(sentences)
    rng.shuffle(order)
    size = (len(order) + folds - 1) // folds
    f1s, exacts, roots, parsed = [], 0, 0, 0
    for fold in range(folds):
        test = order[fold * size:(fold + 1) * size]
        train = [s for s in order if s not in test]
        hg = build_grammar(train, alpha)
        for row in evaluate(test, hg):
            if not row[6]:
                continue
            parsed += 1
            f1s.append(row[3])
            exacts += row[4]
            roots += row[5]
    print(f"5-fold CV (alpha={alpha:g}): parsed={parsed}/{len(sentences)}  "
          f"F1={_mean(f1s):.3f}  exact={exacts}  root-match={roots}/{parsed}")


def _render(n: Node, depth: int = 0) -> str:
    if n.is_lexical:
        return f"({n.cat} {n.surface or ''})"
    return f"({n.cat} {' '.join(_render(c, depth + 1) for c in n.children)})"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--demo", metavar="SUBSTR", default="")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=1.0)
    args = ap.parse_args()
    sentences = [s for f in sorted(CGEL.glob("*.cgel"))
                 for s in parse_cgel_file(str(f))]
    if args.eval:
        rows = evaluate(sentences, build_grammar(sentences, args.alpha))
        f = [r[3] for r in rows if r[6]]
        print(f"self-fit: parsed={sum(1 for r in rows if r[6])}/{len(sentences)}  "
              f"F1={_mean(f):.3f}  exact={sum(1 for r in rows if r[4])}")
        cross_validate(sentences, folds=args.folds, alpha=args.alpha)
    if args.demo:
        hg = build_grammar(sentences, args.alpha)
        for s in sentences:
            if args.demo and args.demo not in s.sent:
                continue
            pr = parse(hg, sentence_tokens(s), sentence_words(s))
            print("\nsent:", s.sent)
            print("yield:", " ".join(sentence_tokens(s)))
            if pr is None:
                print("  (no parse)")
            else:
                print(f"  root={pr.root_cat}  logp={pr.logp:.3f}")
                print("  " + _render(pr.tree))
            if args.demo:
                break


if __name__ == "__main__":
    main()
