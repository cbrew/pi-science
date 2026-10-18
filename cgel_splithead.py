"""Bottom-up, head-driven (Eisner split-head) generative models over CGEL trees.

This is an experiment in building better generative models *from the bottom
up*.  Every CGEL constituent has a single lexical head (the head rule); the
head's *dependents* are the non-head children.  The split-head model of
Eisner (1996) generates, for each head, two sequences of dependents -- one to
the LEFT and one to the RIGHT of the head -- where **each sequence is
explicitly terminated by a STOP symbol**:

    P_L(left seq)  = p_stop(C,L) * prod p_dep((f,D) | C,L)
    P_R(right seq) = p_stop(C,R) * prod p_dep((f,D) | C,R)
    p_stop(C,S) + sum over (f,D) of p_dep((f,D) | C,S) = 1

Because each side is a stopped renewal process, its total mass is exactly 1:

    sum over all sequences  = p_stop * sum_k (sum p_dep)^k = 1.

This is precisely why the normalisation problem we hit with Model B
(`cgel_models.py`) disappears here: B let a node draw an *unbounded* number
of children, so its renormalised child picks could push the branching process
supercritical and force an artificial depth bound.  The split-head model has
no free branching: every head's dependents form a left and a right sequence,
each stopped explicitly, and every dependent is itself anchored to a word of
the **finite observed string**.  The probability of a full analysis is
therefore a proper distribution over the (finite) set of analyses of that
string, no normaliser, no depth bound.

Building bottom up from parts of speech:

1. each lexical word/POS is a potential head;
2. a head projects a category with probability  P(C | POS)   (the head
   rule / projection convention, quantified);
3. on each side the head takes a stopped sequence of dependents
   (function, dependent-category) -- Subj/Det/Marker on the left, for
   instance, Obj/Comp/Mod/Supplement on the right;
4. each dependent is itself a phrase with its own head, so the process
   recurses -- but always inside the word string, so it is finite.

Coordination and other headless/flat constituents (no single head to split
around) are handled by a coarser "flat" mode: the whole child sequence is
generated as one stopped sequence.

The module fits the model by MLE (+ smoothing), verifies the per-side
normalisation analytically and numerically, computes exact per-analysis
log-likelihoods on the attested corpus, and reports the expected number of
dependents per head (finite) as the empirical counterpart of the (absent)
supercriticality problem.

Run:  python3 cgel_splithead.py
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from cgel_reader import Node, Sentence, parse_cgel_file

CGEL = Path(__file__).resolve().parent / "cgel"

# edges that head a projection (the fused determinative / modifier / marker
# heads -- NOT ``Head-Prenucleus``, which marks a fronted {dependent})
HEAD_EDGES = frozenset({"Head", "Det-Head", "Mod-Head", "Marker-Head"})

LOG0 = -math.inf


def _logsum(a: float, b: float) -> float:
    if a == LOG0:
        return b
    if b == LOG0:
        return a
    return max(a, b) + math.log1p(math.exp(-abs(a - b)))


# ---------------------------------------------------------------------------
# extraction: turn an attested tree into per-head left/right dependent
# sequences (the "productive events" of the analysis)
# ---------------------------------------------------------------------------

def _lex_positions(root: Node) -> Tuple[Dict[Node, int], Dict[Node, Tuple[int, int]]]:
    """lexical node -> surface token index; node -> (min, max) token span."""
    pos: Dict[Node, int] = {}
    i = 0
    for n in root.iter_nodes():
        if n.is_lexical:
            pos[n] = i
            i += 1
    spans: Dict[Node, Tuple[int, int]] = {}

    def span(n: Node) -> Tuple[Optional[int], Optional[int]]:
        if n in pos:
            return (pos[n], pos[n])
        if n.is_gap:
            return (None, None)
        lo, hi = 10 ** 9, -1
        for c in n.children:
            a, b = span(c)
            if a is not None:
                lo = min(lo, a)
                hi = max(hi, b)
        spans[n] = (lo, hi)
        return (lo, hi)
    span(root)
    return pos, spans


def _dominant_child(n: Node) -> Optional[Node]:
    """The single child that heads this projection, or None.

    An exactly-one plain ``Head`` child wins; otherwise a fused head edge
    (``Det-Head`` determinative-head, ``Mod-Head``, ``Marker-Head``) is used.
    ``Head-Prenucleus`` is *not* treated as the head here: it marks a fronted
    (displaced) constituent, which is a dependent of the clause, so a
    ``Clause_rel`` carrying both ``Head-Prenucleus`` and ``Head`` is headed by
    the ``Head`` child and the fronted element becomes a left dependent."""
    heads = [c for c in n.children if c.edge in HEAD_EDGES]
    if len(heads) != 1:
        return None
    return heads[0]


def _head_leaf(n: Node) -> Optional[Node]:
    """Follow the head chain down to a lexical leaf (the head word)."""
    cur = n
    while cur.children:
        d = _dominant_child(cur)
        if d is None:
            return None
        cur = d
        if cur.is_lexical:
            return cur
    return cur if cur.is_lexical else None


def iter_events(sentence: Sentence):
    """Yield one event per internal node.

    ``("proj", cat, pos, left_seq, right_seq)`` for a head-driven projection
    with a clean left/right split; ``("flat", cat, seq)`` otherwise
    (coordination, GAP/ambiguous spans, headless).
    ``pos`` is the head word's lexical category (bottom-up anchor); ``cat`` is
    the projection category.  Each dep = (function, category).
    """
    pos, spans = _lex_positions(sentence.root)
    for n in sentence.root.iter_nodes():
        if not n.children:
            continue
        d = _dominant_child(n)
        hlex = _head_leaf(n) if d is not None else None
        hp = pos.get(hlex) if hlex else None
        if hp is None:
            yield ("flat", n.cat,
                   [(c.edge or "<ROOT>", c.cat) for c in n.children])
            continue
        left, right, ambiguous = [], [], False
        for c in n.children:
            if c is d:
                continue
            a, b = spans.get(c, (None, None))
            if a is None:
                ambiguous = True
                break
            if b < hp:
                left.append((c.edge or "?", c.cat))
            elif a > hp:
                right.append((c.edge or "?", c.cat))
            else:
                ambiguous = True
                break
        if ambiguous:
            yield ("flat", n.cat,
                   [(c.edge or "<ROOT>", c.cat) for c in n.children])
        else:
            yield ("proj", n.cat, hlex.cat, tuple(left), tuple(right))


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

class SplitHead:
    """Split-head generative model over CGEL analyses (bottom-up from POS)."""

    L, R = "L", "R"

    def __init__(self, anchor: Dict[Tuple[str, str], float],
                 dep: Dict[Tuple[str, str, Tuple[str, str]], float],
                 stop: Dict[Tuple[str, str], float],
                 flat_dep: Dict[Tuple[str, Tuple[str, str]], float],
                 flat_stop: Dict[str, float]):
        self.anchor = anchor        # (pos, cat) -> P(cat | pos)
        self.dep = dep              # (cat, side, (f, depcat)) -> p_dep
        self.stop = stop            # (cat, side) -> p_stop
        self.flat_dep = flat_dep    # (cat, (f, depcat)) -> p (flat mode)
        self.flat_stop = flat_stop  # cat -> p_stop (flat mode)

    # -- fitting -------------------------------------------------------------
    @classmethod
    def fit(cls, sentences: Iterable[Sentence], alpha: float = 1.0) -> "SplitHead":
        anc = Counter()                          # (pos, cat)
        depc = Counter()                         # (cat, side, (f, D))
        stopc = defaultdict(int)                 # (cat, side)
        fdepc = Counter()                        # (cat, (f, D))
        fstopc = defaultdict(int)                # cat
        for s in sentences:
            for ev in iter_events(s):
                if ev[0] == "proj":
                    _, cat, pcat, left, right = ev
                    anc[(pcat, cat)] += 1
                    for side, seq in ((cls.L, left), (cls.R, right)):
                        stopc[(cat, side)] += 1
                        for f, d in seq:
                            depc[(cat, side, (f, d))] += 1
                else:
                    _, cat, seq = ev
                    fstopc[cat] += 1
                    for f, d in seq:
                        fdepc[(cat, (f, d))] += 1

        def norm(c: Counter, dim: int, a: float) -> dict:
            tot = sum(c.values())
            return {k: (v + a) / (tot + a * dim) for k, v in c.items()}

        # bottom-up anchor: P(projection category | head POS), normalised per POS
        anchor = {}
        by_pos = defaultdict(int)
        ncat_by_pos = defaultdict(set)
        for (p, c), v in anc.items():
            by_pos[p] += v
            ncat_by_pos[p].add(c)
        for p in by_pos:
            for (pp, c) in anc:
                if pp == p:
                    anchor[(p, c)] = (anc[(p, c)] + alpha) \
                        / (by_pos[p] + alpha * len(ncat_by_pos[p]))

        # per-head side model: p_stop(C,S) + sum_events p_dep(C,S,.) = 1
        evset = set(depc)
        dep, stop = {}, {}
        for (cat, side) in stopc:
            cells = [k[2] for k in evset if k[0] == cat and k[1] == side]
            tot = stopc[(cat, side)] + sum(depc[(cat, side, cell)]
                                           for cell in cells)
            ntypes = len(set(cells))
            stop[(cat, side)] = (stopc[(cat, side)] + alpha) \
                / (tot + alpha * (ntypes + 1))
            for cell in cells:
                dep[(cat, side, cell)] = (depc[(cat, side, cell)] + alpha) \
                    / (tot + alpha * (ntypes + 1))

        # flat mode: the whole child sequence from one stopped process, so
        # p_stop(C) + sum_events p_flat(C,.) = 1 as well
        flat_dep, flat_stop = {}, {}
        for cat in fstopc:
            cells = [k[1] for k in fdepc if k[0] == cat]
            tot = fstopc[cat] + sum(fdepc[(cat, cell)] for cell in cells)
            ntypes = len(set(cells))
            flat_stop[cat] = (fstopc[cat] + alpha) / (tot + alpha * (ntypes + 1))
            for cell in cells:
                flat_dep[(cat, cell)] = (fdepc[(cat, cell)] + alpha) \
                    / (tot + alpha * (ntypes + 1))
        return cls(anchor, dep, stop, flat_dep, flat_stop)

    # -- scoring -------------------------------------------------------------
    def _side(self, cat: str, side: str, seq) -> float:
        lp = math.log(self.stop[(cat, side)])
        for f, d in seq:
            lp += math.log(self.dep[(cat, side, (f, d))])
        return lp

    def loglik(self, sentence: Sentence) -> float:
        total = 0.0
        for ev in iter_events(sentence):
            if ev[0] == "proj":
                _, cat, pcat, left, right = ev
                total += math.log(self.anchor[(pcat, cat)])
                total += self._side(cat, self.L, left)
                total += self._side(cat, self.R, right)
            else:
                _, cat, seq = ev
                lp = math.log(self.flat_stop[cat])
                for f, d in seq:
                    lp += math.log(self.flat_dep[(cat, (f, d))])
                total += lp
        return total

    # -- normalisation diagnostics -------------------------------------------
    def check_normalization(self) -> dict:
        """Per (cat, side): confirm p_stop + sum p_dep = 1 and the total mass
        of all argument sequences is 1; expected number of dependents."""
        rows = []
        keys = set(self.stop)
        for (cat, side) in sorted(keys):
            evs = {k: v for k, v in self.dep.items()
                   if k[0] == cat and k[1] == side}
            s = self.stop[(cat, side)]
            sum_dep = sum(evs.values())
            # sum over all sequences of p_stop * prod p_dep = p_stop * sum_k
            # (sum_dep)^k = p_stop/(1 - sum_dep) -- must equal 1
            seq_mass = s / (1 - sum_dep) if sum_dep < 1 else float("inf")
            rows.append((cat, side, len(evs), s, sum_dep, s + sum_dep,
                         seq_mass, sum_dep / s))
        return rows


def worked_example(model: SplitHead, sentence: Sentence) -> None:
    """Show one analysis decomposed bottom-up into per-head left/right
    argument sequences -- the derivational events the model generates."""
    pos, _ = _lex_positions(sentence.root)
    text = {n: n.surface for n in pos}

    def show(n: Node, depth: int) -> None:
        pad = "  " * depth
        if not n.children:
            return
        d = _dominant_child(n)
        hlex = _head_leaf(n) if d is not None else None
        if hlex is None:
            seq = ", ".join(f"{c.edge}:{c.cat}" for c in n.children)
            print(f"{pad}{n.cat} [flat]  ({seq})")
            for c in n.children:
                show(c, depth + 1)
            return
        hw = text.get(hlex, "?")
        # recompute left/right sequences as in iter_events
        hp = pos[hlex]
        _, spans = _lex_positions_from(n, pos)
        left, right = [], []
        for c in n.children:
            if c is d:
                continue
            a, b = spans.get(c, (None, None))
            if b is not None and b < hp:
                left.append(f"{c.edge}:{c.cat}")
            else:
                right.append(f"{c.edge}:{c.cat}")
        print(f"{pad}{n.cat}  head:<{hlex.cat} '{hw}'>")
        print(f"{pad}    left : {' | '.join(left) or '-'}")
        print(f"{pad}    right: {' | '.join(right) or '-'}")
        for c in n.children:
            show(c, depth + 1)
    show(sentence.root, 0)


def _lex_positions_from(n: Node, pos: Dict):
    """Reuse the token-position map (subtree spans) for a node."""
    spans = {}
    def span(x: Node):
        if x in pos:
            return (pos[x], pos[x])
        if x.is_gap:
            return (None, None)
        lo, hi = 10 ** 9, -1
        for c in x.children:
            a, b = span(c)
            if a is not None:
                lo = min(lo, a)
                hi = max(hi, b)
        spans[x] = (lo, hi)
        return (lo, hi)
    span(n)
    return n, spans


def evaluate(sentences: List[Sentence], model: SplitHead) -> dict:
    lls = [model.loglik(s) for s in sentences]
    toks = [sum(1 for t in s.tokens()) for s in sentences]
    return {
        "n": len(sentences),
        "avg_loglik": statistics.mean(lls),
        "avg_per_token": statistics.mean(
            l / max(1, t) for l, t in zip(lls, toks)),
        "lls": lls,
    }


def main() -> None:
    print("loading corpus...", flush=True)
    sentences = [s for f in sorted(CGEL.glob("*.cgel"))
                 for s in parse_cgel_file(str(f))]
    model = SplitHead.fit(sentences, alpha=1.0)
    res = evaluate(sentences, model)

    # count events / coverage
    proj = flat = 0
    for s in sentences:
        for ev in iter_events(s):
            proj += ev[0] == "proj"
            flat += ev[0] == "flat"
    print(f"head-driven projections: {proj}   flat (coord/gap/ambiguous): {flat}")

    print("\nper-side normalisation of the split-head model "
          "[(cat,side) events  p_stop  sum p_dep  p_stop+sum  seq-mass  E[#deps]]")
    for cat, side, nev, s, sd, tot, mass, expect in model.check_normalization():
        ok = abs(tot - 1.0) < 1e-9 and abs(mass - 1.0) < 1e-9
        print(f"  {cat:11s} {side}  {nev:3d}  {s:6.4f} {sd:7.4f}  {tot:6.4f}  "
              f"{mass:6.4f}  {expect:6.2f}  {'OK' if ok else '!!'}")
    print("  (seq-mass = sum over ALL argument sequences = p_stop * sum_k "
          "(sum p_dep)^k; should be exactly 1 for every side)")

    print("\nattested-corpus log-likelihood (bottom-up split-head):")
    print(f"  sentences: {res['n']}")
    print(f"  avg log P(tree)           : {res['avg_loglik']:.3f}")
    print(f"  avg log P per surface token: {res['avg_per_token']:.3f}")

    # directionality: the most-preferred dependent on each side of each head
    print("\nstrongest left / right argument preferences per head category "
          "(function:category, p x E[#deps on that side]):")
    seen = set()
    for (cat, side, cell), p in sorted(model.dep.items(),
                                       key=lambda kv: -kv[1]):
        if (cat, side) in seen:
            continue
        seen.add((cat, side))
        stop = model.stop[(cat, side)]
        k = p / stop          # expected number of this kind of dependent
        if k < 0.02:
            continue
        f, d = cell
        print(f"  {cat:9s} {side} → {f:12s} {d:9s}  p={p:.3f}  E[kind]={k:.2f}")

    def _has_gap(n: Node) -> bool:
        return n.is_gap or any(_has_gap(c) for c in n.children)
    gapfree = [s for s in sentences if not _has_gap(s.root)]
    ex = min(gapfree, key=lambda s: len(s.tokens())) if gapfree else sentences[0]
    if ex:
        print("\n" + "=" * 74)
        print("worked example · bottom-up head/argument decomposition of:")
        print("  ", ex.sent)
        print("=" * 74)
        worked_example(model, ex)
        print(f"\nlog P(this analysis) = {model.loglik(ex):.3f}")

    print("\ncomparison with the earlier models (avg log P(attested)). NOTE: "
          "the models live in different probability spaces, so absolute "
          "numbers are not directly comparable; the split-head is the only one "
          "that is a fully normalised bottom-up generative model with no depth "
          "bound or partition-function term.")
    print(f"  skeleton-conditional A : -102.69   B :  -42.20")
    print(f"  structural generative  :  -229.67   B: -154.48")
    print(f"  split-head (this)      : {res['avg_loglik']:.2f} per sentence, "
          f"{res['avg_per_token']:.2f} per token")


if __name__ == "__main__":
    main()
