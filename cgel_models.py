"""Probability models over CGEL treebank analyses.

Two models assign probabilities to the *labelled analyses* of a sentence.
The linguistic skeleton (tree shape) of a sentence is the one attested in the
corpus; both models score the label assignments of that skeleton:

  Model A  --  labels are independent.  Every structural node independently
               draws a category from P(cat) and an incoming function label
               from P(edge): a product of independent multinomials, i.e. a
               log-linear model whose only features are per-node category and
               edge indicators (no interactions, no structure).  It assigns
               non-zero probability to grammatically impossible analyses
               (e.g. ``N`` directly under ``Clause :Subj``).

  Model B  --  the same feature family, but *support restricted to analyses
               that follow the discovered conventions* (head rule, X-bar
               projection skeleton, function-parent/function-child
               licensing): everything else has probability exactly 0.
               Because the constraints are local to adjacent nodes
               (``allowed(parent_cat, edge, cat)``), the partition function of
               B, its node marginals and its samples are computed *exactly*
               by dynamic programming on the skeleton tree.

Features / weights: per variable node, indicator of its category and of its
incoming edge (the root node's incoming edge is structural, not part of the
label space).  Lexical (word) categories and GAP nodes are fixed by the words
/ indices.

CLI:

  python3 cgel_models.py --eval            # likelihoods, conformity, samples
  python3 cgel_models.py --demo SUBSTR     # MAP analyses under A and B
  python3 cgel_models.py --fit-b           # MLE training of log-linear B
  python3 cgel_models.py --structured      # generativer (shape+labels) A and B

Pure standard library.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from cgel_grammar import ALL_CATS, EDGES, ROOT, ROOT_CATS, allowed
from cgel_reader import Node, Sentence, parse_cgel_file

CGEL = Path(__file__).resolve().parent / "cgel"

_CATS = sorted(ALL_CATS)
_EDGES = sorted(EDGES)
N_FEAT = len(_CATS) + len(_EDGES)

LOG0 = -math.inf


def _logsum(a: float, b: float) -> float:
    if a == LOG0:
        return b
    if b == LOG0:
        return a
    return max(a, b) + math.log1p(math.exp(-abs(a - b)))


def _logaddexp(items: Iterable[float]) -> float:
    z = LOG0
    for x in items:
        z = _logsum(z, x)
    return z


def _normalized_logdist(d: Dict[str, float]) -> Dict[str, float]:
    z = _logaddexp(d.values())
    return {k: v - z for k, v in d.items() if v != LOG0}


# --------------------------------------------------------------------------
# skeleton
# --------------------------------------------------------------------------

@dataclass
class Slot:
    """One node of a skeleton.  ``fixed_cat`` is not None for lexical / GAP
    nodes; variable nodes carry (category, edge) labels drawn by the
    models."""
    fixed_cat: Optional[str] = None
    children: "List[Slot]" = field(default_factory=list)
    node: Optional[Node] = None  # attested node (for scoring / decoding)

    __hash__ = object.__hash__

    @property
    def is_variable(self) -> bool:
        return self.fixed_cat is None


def make_skeleton(node: Node) -> Slot:
    if "t" in node.feats or node.is_gap:
        return Slot(fixed_cat=node.cat, children=[], node=node)
    return Slot(fixed_cat=None, children=[make_skeleton(c) for c in node.children],
                node=node)


def iter_slots(slot: Slot) -> Iterable[Slot]:
    yield slot
    for c in slot.children:
        yield from iter_slots(c)


def attested_assignment(sentence: Sentence) -> Dict[Node, Tuple[str, str]]:
    a: Dict[Node, Tuple[str, str]] = {}
    for i, slot in enumerate(iter_slots(make_skeleton(sentence.root))):
        if slot.is_variable and slot.node is not None:
            a[slot.node] = (slot.node.cat, ROOT if i == 0 else (slot.node.edge or ROOT))
    return a


def is_conforming(assign: Dict[Node, Tuple[str, str]], sk: Slot,
                  allow: Callable = allowed) -> bool:
    def rec(slot: Slot, parent_cat: str) -> bool:
        if slot.fixed_cat is not None:
            e = slot.node.edge if slot.node is not None and slot.node.edge else ROOT
            if not allow(parent_cat, e, slot.fixed_cat):
                return False
            return all(rec(c, slot.fixed_cat) for c in slot.children)
        cat, edge = assign[slot.node]
        if not allow(parent_cat, edge, cat):
            return False
        return all(rec(c, cat) for c in slot.children)
    return rec(sk, ROOT)


def assignment_to_tree(sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> Node:
    def rec(slot: Slot) -> Node:
        if slot.is_variable and slot.node is not None:
            cat, edge = assign[slot.node]
            edge = None if edge == ROOT else edge
            return Node(cat=cat, edge=edge,
                        children=[rec(c) for c in slot.children])
        n = slot.node or Node("?")
        return Node(cat=n.cat, index=n.index, edge=n.edge,
                    feats={k: list(v) for k, v in n.feats.items()},
                    children=[rec(c) for c in slot.children])
    return rec(sk)


# --------------------------------------------------------------------------
# Model A: independent labels
# --------------------------------------------------------------------------

class ModelA:
    """Product of independent multinomials over categories and edges.

    ``p_cat`` / ``p_edge`` are normalised distributions (MLE + smoothing over
    the corpus).  P(labelling) = prod P(cat) * prod P(edge) over variable
    nodes; the root node contributes only a category draw.  Normalised by
    construction (Z_A = 1).
    """

    def __init__(self, p_cat: Dict[str, float], p_edge: Dict[str, float]):
        self.p_cat = p_cat
        self.p_edge = p_edge

    @classmethod
    def fit(cls, sentences: Iterable[Sentence], alpha: float = 1.0) -> "ModelA":
        cc: Counter = Counter()
        ec: Counter = Counter()
        for s in sentences:
            slots = list(iter_slots(make_skeleton(s.root)))
            for i, slot in enumerate(slots):
                if not slot.is_variable or slot.node is None:
                    continue
                cc[slot.node.cat] += 1
                if i > 0:
                    ec[slot.node.edge or ROOT] += 1
        p_cat = {c: (cc[c] + alpha) / (sum(cc.values()) + alpha * len(_CATS))
                 for c in _CATS}
        p_edge = {e: (ec[e] + alpha) / (sum(ec.values()) + alpha * len(_EDGES))
                  for e in _EDGES}
        return cls(p_cat, p_edge)

    def logp(self, sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> float:
        p = 0.0
        for i, slot in enumerate(iter_slots(sk)):
            if not slot.is_variable or slot.node is None:
                continue
            cat, edge = assign[slot.node]
            p += math.log(self.p_cat[cat])
            if i > 0:
                p += math.log(self.p_edge[edge])
        return p

    def prob(self, sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> float:
        return math.exp(self.logp(sk, assign))

    def sample(self, sk: Slot, n: int = 1,
               rng: random.Random = random) -> List[Dict[Node, Tuple[str, str]]]:
        out: List[Dict[Node, Tuple[str, str]]] = []
        for _ in range(n):
            assign: Dict[Node, Tuple[str, str]] = {}
            for i, slot in enumerate(iter_slots(sk)):
                if not slot.is_variable or slot.node is None:
                    continue
                c = rng.choice(_CATS)
                e = ROOT if i == 0 else rng.choice(_EDGES)
                assign[slot.node] = (c, e)
            out.append(assign)
        return out


# --------------------------------------------------------------------------
# Model B: conventions as hard constraints, exact inference on the skeleton
# --------------------------------------------------------------------------

class ModelB:
    """Log-linear model restricted to convention-conforming analyses.

    ``weight_cat`` / ``weight_edge`` are log weights; a node contributes
    ``exp(w_cat(cat) + w_edge(edge))``.  Normalisation, node marginals,
    sampling and Viterbi decoding are computed exactly by dynamic programming
    on the skeleton (the conventions are local: ``allow(parent_cat, edge,
    cat)``).
    """

    def __init__(self, weight_cat: Dict[str, float], weight_edge: Dict[str, float],
                 allow: Callable = allowed):
        self.weight_cat = dict(weight_cat)
        self.weight_edge = dict(weight_edge)
        self.allow = allow
        self.cells: Dict[str, List[Tuple[str, str]]] = {}
        for pc in [ROOT] + _CATS:
            if pc == ROOT:
                self.cells[pc] = [(ROOT, c) for c in ROOT_CATS]
            else:
                self.cells[pc] = [(e, c) for e in _EDGES for c in _CATS
                                  if self.allow(pc, e, c)]

    # ------------------------------------------------------------------ DP --

    def up_messages(self, sk: Slot) -> Tuple[Dict[Slot, Dict[str, float]], float]:
        """(up[slot][parent_cat], logZ): log-masses of subtrees given the
        parent's category; logZ sums over the root."""
        up: Dict[Slot, Dict[str, float]] = {}

        def rec(slot: Slot) -> Dict[str, float]:
            child_log: Dict[str, float] = {c: 0.0 for c in _CATS}
            for child in slot.children:
                cm = rec(child)
                for c in _CATS:
                    v = cm.get(c, LOG0)
                    child_log[c] = v if v == LOG0 else (child_log[c] + v)
            if slot.fixed_cat is not None:
                e = slot.node.edge if slot.node is not None and slot.node.edge else ROOT
                msg: Dict[str, float] = {}
                for pc in _CATS:
                    if self.allow(pc, e, slot.fixed_cat):
                        msg[pc] = child_log[slot.fixed_cat]
            else:
                msg = {}
                for pc in _CATS:
                    m = LOG0
                    for e, c in self.cells[pc]:
                        v = child_log[c]
                        if v != LOG0:
                            m = _logsum(m, self.weight_cat[c]
                                        + (self.weight_edge[e] if e != ROOT else 0.0)
                                        + v)
                    if m != LOG0:
                        msg[pc] = m
            up[slot] = msg
            return msg

        rec(sk)
        z = LOG0
        for e, c in self.cells[ROOT]:
            v = self.weight_cat[c]
            for child in sk.children:
                m = up[child].get(c, LOG0)
                v += m if m != LOG0 else LOG0
            z = _logsum(z, v)
        return up, z

    def score(self, sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> float:
        z = 0.0
        for i, slot in enumerate(iter_slots(sk)):
            if not slot.is_variable or slot.node is None:
                continue
            cat, edge = assign[slot.node]
            z += self.weight_cat[cat]
            if i > 0:
                z += self.weight_edge[edge]
        return z

    def logp(self, sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> float:
        # hard support: only convention-conforming analyses carry mass
        if not is_conforming(assign, sk, self.allow):
            return LOG0
        _, z = self.up_messages(sk)
        return self.score(sk, assign) - z

    def prob(self, sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> float:
        return math.exp(self.logp(sk, assign))

    # ------------------------------------------------------------- marginals --

    def _children_sum(self, up: Dict[Slot, Dict[str, float]],
                      slot: Slot) -> Dict[str, float]:
        """Per-cat log-mass of the subtree below ``slot`` (precomputed table)."""
        m: Dict[str, float] = {c: 0.0 for c in _CATS}
        for child in slot.children:
            cm = up[child]
            for c in _CATS:
                v = cm.get(c, LOG0)
                m[c] += v if v != LOG0 else LOG0
        return m

    def marginals(self, sk: Slot):
        """Per variable node: dicts of log P(cat) and log P(edge)."""
        up, _ = self.up_messages(sk)
        cat_marg: Dict[Slot, Dict[str, float]] = {}
        edge_marg: Dict[Slot, Dict[str, float]] = {}

        def visit(slot: Slot, parent_cat_dist: Dict[str, float]) -> None:
            cacc: Dict[str, float] = {c: LOG0 for c in _CATS}
            eacc: Dict[str, float] = {e: LOG0 for e in _EDGES}
            cm = self._children_sum(up, slot)
            for pcat, p in parent_cat_dist.items():
                if p == LOG0:
                    continue
                for e, c in self.cells[pcat]:
                    v = cm[c]
                    if v == LOG0:
                        continue
                    w = self.weight_cat[c] + (self.weight_edge[e] if e != ROOT else 0.0)
                    v = p + w + v
                    cacc[c] = _logsum(cacc[c], v)
                    if e != ROOT:
                        eacc[e] = _logsum(eacc[e], v)
            cat_marg[slot] = _normalized_logdist(cacc)
            edge_marg[slot] = _normalized_logdist(eacc)
            for child in slot.children:
                visit(child, cat_marg[slot])

        visit(sk, {ROOT: 0.0})
        return cat_marg, edge_marg

    # --------------------------------------------------------------- sampling --

    def sample(self, sk: Slot, n: int = 1,
               rng: random.Random = random) -> List[Dict[Node, Tuple[str, str]]]:
        up, _ = self.up_messages(sk)

        def child_mass(slot: Slot, cat: str) -> float:
            m = 0.0
            for child in slot.children:
                v = up[child].get(cat, LOG0)
                m += v if v != LOG0 else LOG0
            return m

        out: List[Dict[Node, Tuple[str, str]]] = []
        for _ in range(n):
            assign: Dict[Node, Tuple[str, str]] = {}

            def rec(slot: Slot, parent_cat: str) -> None:
                if slot.is_variable and slot.node is not None:
                    cells = self.cells[parent_cat]
                    ws = [self.weight_cat[c]
                          + (self.weight_edge[e] if e != ROOT else 0.0)
                          + child_mass(slot, c) for e, c in cells]
                    mx = max(ws) if ws else 0.0
                    (e, c) = rng.choices(cells,
                                         weights=[math.exp(w - mx) for w in ws],
                                         k=1)[0]
                    assign[slot.node] = (c, e)
                else:
                    c = slot.fixed_cat
                    e = slot.node.edge if slot.node is not None and slot.node.edge else ROOT
                for child in slot.children:
                    rec(child, c)
            rec(sk, ROOT)
            out.append(assign)
        return out

    # ----------------------------------------------------------------- Viterbi --

    def argmax(self, sk: Slot) -> Dict[Node, Tuple[str, str]]:
        """Viterbi decoding, memoised on (slot, parent_cat). The optimal
        label of each slot depends on the parent's category, so decisions are
        stored per (slot, parent_cat) and backtracked from the root (a
        per-node store would be overwritten by non-MAP parent categories)."""
        memo: Dict[Tuple[Slot, str], float] = {}
        decisions: Dict[Tuple[Slot, str], Tuple[str, str]] = {}

        def children_tot(slot: Slot, cat: str) -> float:
            """Best total mass of slot's children given slot's own cat."""
            t = 0.0
            for child in slot.children:
                v = rec(child, cat)
                t += v if v != LOG0 else LOG0
            return t

        def rec(slot: Slot, parent_cat: str) -> float:
            key = (slot, parent_cat)
            if key in memo:
                return memo[key]
            if slot.fixed_cat is not None:
                e = slot.node.edge if slot.node is not None and slot.node.edge else ROOT
                if not self.allow(parent_cat, e, slot.fixed_cat):
                    memo[key] = LOG0
                    return LOG0
                memo[key] = children_tot(slot, slot.fixed_cat)
                return memo[key]
            bc, be, bv = None, None, LOG0
            for e, c in self.cells[parent_cat]:
                v = (self.weight_cat[c]
                     + (self.weight_edge[e] if e != ROOT else 0.0)
                     + children_tot(slot, c))
                if v > bv:
                    bv, bc, be = v, c, e
            if bc is not None:
                decisions[key] = (bc, be)
            memo[key] = bv
            return bv

        if rec(sk, ROOT) == LOG0:
            return {}
        best: Dict[Node, Tuple[str, str]] = {}

        def back(slot: Slot, parent_cat: str) -> None:
            if slot.fixed_cat is not None:
                for child in slot.children:
                    back(child, slot.fixed_cat)
                return
            c, e = decisions[(slot, parent_cat)]
            best[slot.node] = (c, e)
            for child in slot.children:
                back(child, c)
        back(sk, ROOT)
        return best


# --------------------------------------------------------------------------
# fitting (MLE for Model B) and evaluation
# --------------------------------------------------------------------------

def expected_features(sk: Slot, model: ModelB) -> List[float]:
    cat_marg, edge_marg = model.marginals(sk)
    f = [0.0] * N_FEAT
    for i, slot in enumerate(iter_slots(sk)):
        if not slot.is_variable or slot.node is None:
            continue
        for c, v in cat_marg[slot].items():
            f[_CATS.index(c)] += math.exp(v)
        if i > 0:
            for e, v in edge_marg[slot].items():
                f[len(_CATS) + _EDGES.index(e)] += math.exp(v)
    return f


def observed_features(sk: Slot, assign: Dict[Node, Tuple[str, str]]) -> List[float]:
    f = [0.0] * N_FEAT
    for i, slot in enumerate(iter_slots(sk)):
        if not slot.is_variable or slot.node is None:
            continue
        cat, edge = assign[slot.node]
        f[_CATS.index(cat)] += 1.0
        if i > 0:
            f[len(_CATS) + _EDGES.index(edge)] += 1.0
    return f


def fit_loglinear(sentences: List[Sentence], iterations: int = 150, lr: float = 0.1,
                  l2: float = 1e-4, verbose: bool = False) -> ModelB:
    """MLE for Model B (constrained support) by gradient ascent (Adam-lite).

    dL/dw = sum_skeletons E[f] - sum_skeletons f(attested);
    E[f] computed by the exact DP.
    """
    w = [0.0] * N_FEAT

    def make_model() -> ModelB:
        wc = {c: w[_CATS.index(c)] for c in _CATS}
        we = {e: w[len(_CATS) + _EDGES.index(e)] for e in _EDGES}
        return ModelB(wc, we)

    skeletons = [make_skeleton(s.root) for s in sentences]
    assigns = [attested_assignment(s) for s in sentences]
    obs = [0.0] * N_FEAT
    for sk, a in zip(skeletons, assigns):
        fo = observed_features(sk, a)
        for i in range(N_FEAT):
            obs[i] += fo[i]
    m = [0.0] * N_FEAT
    v = [0.0] * N_FEAT
    model = make_model()
    nll = 0.0
    for sk, a in zip(skeletons, assigns):
        nll -= model.logp(sk, a)
    for it in range(iterations):
        grad = [0.0] * N_FEAT
        for sk in skeletons:
            ef = expected_features(sk, model)
            for i in range(N_FEAT):
                grad[i] += ef[i] - obs[i]
        for i in range(N_FEAT):
            g = grad[i] + l2 * w[i]
            m[i] = 0.9 * m[i] + 0.1 * g
            v[i] = 0.999 * v[i] + 0.001 * g * g
            w[i] -= lr * m[i] / (math.sqrt(v[i]) + 1e-8)
        model = make_model()
        if verbose and (it % 25 == 0 or it == iterations - 1):
            nll = 0.0
            for sk, a in zip(skeletons, assigns):
                nll -= model.logp(sk, a)
            gn = math.sqrt(sum(g * g for g in grad))
            print(f"  iter {it:4d}  NLL {nll:10.1f}  |grad| {gn:8.1f}")
    if verbose:
        nll = 0.0
        for sk, a in zip(skeletons, assigns):
            nll -= model.logp(sk, a)
        print(f"  final NLL {nll:10.1f}")
    return model


def evaluate(sentences: List[Sentence], model_a: ModelA, model_b: ModelB,
             n_samples: int = 200, seed: int = 1) -> dict:
    """Per-sentence stats over the attested analyses."""
    rng = random.Random(seed)
    rows = []
    for s in sentences:
        sk = make_skeleton(s.root)
        a = attested_assignment(s)
        la = model_a.logp(sk, a)
        lb = model_b.logp(sk, a)
        zb_over_za = math.exp(la - lb)          # Z_A == 1, so this is Z_B
        frac = _mc_conform(model_a, sk, n_samples, rng)
        rows.append((s.sent_id,
                     sum(1 for _ in iter_slots(sk) if _.is_variable),
                     la, lb, zb_over_za, frac))
    n = len(rows)
    avg_a = statistics.mean(r[2] for r in rows)
    avg_b = statistics.mean(r[3] for r in rows)
    return {
        "n": n,
        "avg_logp_A": avg_a,
        "avg_logp_B": avg_b,
        "avg_log_gain": avg_b - avg_a,
        "median_Z_B": statistics.median(r[4] for r in rows),
        "median_MC_conform_A": statistics.median(r[5] for r in rows),
        "rows": rows,
    }


def _mc_conform(model: ModelA, sk: Slot, n: int, rng: random.Random) -> float:
    ok = 0
    for assign in model.sample(sk, n, rng):
        if is_conforming(assign, sk):
            ok += 1
    return ok / n


# --------------------------------------------------------------------------
# structural (generative) models: shape AND labels
# --------------------------------------------------------------------------
# The skeleton-conditional Model A / Model B above score label assignments to
# an *attested* skeleton.  The structural models instead GENERATE the whole
# tree -- its branching (shape) and its labels -- as a sub-critical branching
# process, so the probability of a full analysis reflects its structure too.
#   * root category ~ p_root
#   * at every node: degree k ~ p_deg, then each child (edge, cat) is drawn
#       -- Model A: from the independent product p_cat * p_edge;
#       -- Model B: from p_cat * p_edge renormalised over the
#          convention-licensed child cells of that parent (so B never
#          generates a tree that violates the head rule / X-bar / function
#          licensing).
# Leaves are lexical (word) categories / GAPs; the words themselves are not
# generated, so the model is a pure-syntax generative grammar.


def fit_structured(sentences: Iterable[Sentence], alpha: float = 1.0,
                   max_depth: Optional[int] = None):
    """Fit the structural models as a single-type branching process: every
    node draws its number of children (degree) from the corpus's degree
    distribution; leaf-ness emerges by drawing degree 0.  Model B draws each
    child from ``p_cat * p_edge`` renormalised over the *licensed* child
    cells of its parent, so it never places mass on convention-violating
    analyses.  Both are normalised over trees of depth <= ``max_depth``
    (default: the deepest tree in the corpus), which keeps the partition
    finite even though B's renormalised child picks are supercritical.
    The probability of a full tree thus reflects its SHAPE (degrees on every
    node) as well as its labels."""
    rc, cc, ec, dc = Counter(), Counter(), Counter(), Counter()
    best_depth = 0
    for s in sentences:
        rc[s.root.cat] += 1
        stack = [s.root]
        while stack:
            n = stack.pop()
            dc[len(n.children)] += 1
            for ch in n.children:
                cc[ch.cat] += 1
                ec[ch.edge or ROOT] += 1
                stack.append(ch)
        _, d = _tree_depth(s.root)
        best_depth = max(best_depth, d)
    if max_depth is None:
        max_depth = best_depth
    p_root = {c: (rc[c] + alpha) / (sum(rc.values()) + alpha * len(ROOT_CATS))
              for c in ROOT_CATS}
    p_cat = {c: (cc[c] + alpha) / (sum(cc.values()) + alpha * len(_CATS))
             for c in _CATS}
    p_edge = {e: (ec[e] + alpha) / (sum(ec.values()) + alpha * len(_EDGES))
              for e in _EDGES}
    dmin, dmax = min(dc), max(dc)
    p_deg = {d: (dc[d] + alpha) / (sum(dc.values()) + alpha * (dmax - dmin + 1))
             for d in range(dmin, dmax + 1)}
    return (StructuredModel(p_root, p_cat, p_edge, p_deg, mode="A",
                            max_depth=max_depth),
            StructuredModel(p_root, p_cat, p_edge, p_deg, mode="B",
                            max_depth=max_depth))


def _tree_depth(root: Node) -> Tuple[int, int]:
    """(count, depth) of a tree subtree."""
    count, depth = 1, 0
    for c in root.children:
        cc, dd = _tree_depth(c)
        count += cc
        depth = max(depth, dd + 1)
    return count, depth


class StructuredModel:
    """A generative model over whole trees (structure + labels)."""

    def __init__(self, p_root: Dict[str, float], p_cat: Dict[str, float],
                 p_edge: Dict[str, float], p_deg: Dict[int, float],
                 mode: str = "A", max_depth: int = 25,
                 allow: Callable = allowed):
        self.mode = mode.upper()
        self.p_root = p_root
        self.p_cat = p_cat
        self.p_edge = p_edge
        self.p_deg = p_deg
        self.allow = allow
        self.mu = sum(d * p for d, p in p_deg.items())   # sub-critical iff < 1
        self.max_depth = max_depth
        # mode B: per-parent log-probability of each licensed child cell;
        # mode A: parent-independent (computed on the fly from p_cat * p_edge)
        self._q: Dict[str, Dict[Tuple[str, str], float]] = {}
        if self.mode == "B":
            for pc in _CATS:
                out = {}
                for e in _EDGES:
                    for c in _CATS:
                        if self.allow(pc, e, c):
                            if p_cat[c] > 0 and p_edge[e] > 0:
                                out[(e, c)] = math.log(p_cat[c] * p_edge[e])
                z = _logaddexp(out.values())
                self._q[pc] = {cell: w - z for cell, w in out.items()}
        self._logZ, self._exp_size = self._partitions()

    # ---- scoring -----------------------------------------------------------
    def _pick(self, parent_cat: str, edge: str, cat: str) -> float:
        if self.mode == "A":
            return math.log(self.p_cat[cat]) + math.log(self.p_edge[edge])
        return self._q.get(parent_cat, {}).get((edge, cat), LOG0)

    def logp(self, root: Node) -> float:
        """log P(tree) = unnormalised tree weight - log Z (both exact; the
        partition is over all trees of depth <= max_depth)."""
        total = (math.log(self.p_root[root.cat])
                 if self.p_root.get(root.cat) else LOG0)
        stack = [root]
        while stack:
            n = stack.pop()
            total += math.log(self.p_deg[len(n.children)])
            for ch in n.children:
                e = ch.edge or ROOT
                p = self._pick(n.cat, e, ch.cat)
                if p == LOG0:
                    return LOG0
                total += p
                stack.append(ch)
        return total - self._logZ

    def prob(self, root: Node) -> float:
        return math.exp(self.logp(root))

    # ---- sampling (top-down) -----------------------------------------------
    def _draw_cat(self, rng) -> str:
        return rng.choices(list(self.p_cat), weights=list(self.p_cat.values()))[0]

    def _draw_degree(self, rng) -> int:
        return rng.choices(list(self.p_deg), weights=list(self.p_deg.values()))[0]

    def _draw_child(self, parent_cat: str, rng):
        if self.mode == "A":
            e = rng.choices(list(self.p_edge), weights=list(self.p_edge.values()))[0]
            c = self._draw_cat(rng)
            return e, c
        q = self._q.get(parent_cat)
        if not q:
            return None
        pool = list(q)
        w = [math.exp(v) for v in q.values()]
        return rng.choices(pool, weights=w, k=1)[0]

    def sample(self, rng: random.Random = random, cap: int = 800) -> Node:
        r = rng.choices(list(self.p_root), weights=list(self.p_root.values()))[0]
        root = Node(cat=r)
        count = 1

        def grow(n: Node, remaining: int) -> None:
            nonlocal count
            if remaining <= 0 or count >= cap:
                return
            k = self._draw_degree(rng)
            for _ in range(k):
                if count >= cap:
                    return
                child = self._draw_child(n.cat, rng)
                if child is None:
                    return
                e, c = child
                node = Node(cat=c, edge=None if e == ROOT else e)
                n.children.append(node)
                count += 1
                grow(node, remaining - 1)
        grow(root, self.max_depth)
        return root

    # ---- exact partition & expected size over the depth-bounded space ------ 
    def _child_logmass(self, cat: str, T: Dict[str, float]) -> float:
        """log of expected subtree mass over the children of ``cat``."""
        if self.mode == "A":
            return _logaddexp(math.log(self.p_cat[cc]) + T[cc] for cc in _CATS)
        return _logaddexp(w + T[cc] for (e, cc), w in self._q[cat].items())

    def _child_size(self, cat: str, S: Dict[str, float]) -> float:
        """expected subtree node count over the children of ``cat`` (linear)."""
        if self.mode == "A":
            return sum(self.p_cat[cc] * S[cc] for cc in _CATS)
        return sum(math.exp(w) * S[cc] for (e, cc), w in self._q[cat].items())

    def _partitions(self) -> Tuple[float, float]:
        """(log Z, expected node count) over all trees of depth <= max_depth.
        Z_D(d) = sum_k p_deg(k) * childmass^k, iterated over depths."""
        T_prev = {c: LOG0 for c in _CATS}    # depth -1: no subtree
        S_prev = {c: 0.0 for c in _CATS}     # depth -1: 0 nodes
        for _ in range(self.max_depth + 1):
            T = {}
            S = {}
            for c in _CATS:
                im = self._child_logmass(c, T_prev)
                m = LOG0
                for k, pk in self.p_deg.items():
                    if im == LOG0:
                        term = math.log(pk) if k == 0 else LOG0
                    else:
                        term = math.log(pk) + k * im
                    m = _logsum(m, term)
                T[c] = m
                S[c] = 1.0 + self.mu * self._child_size(c, S_prev)
            T_prev, S_prev = T, S
        logz = _logaddexp(math.log(self.p_root[c]) + T_prev[c]
                          for c in ROOT_CATS)
        exp_size = sum(self.p_root[c] * S_prev[c] for c in ROOT_CATS)
        return logz, exp_size

    def conforms(self, root: Node) -> bool:
        """Every edge (parent.cat, edge, child.cat) is licensed.  Children of
        the root are checked against the root's own category; only the root
        itself has no incoming edge."""
        stack = [(ch, root.cat) for ch in root.children]
        while stack:
            ch, pc = stack.pop()
            if not self.allow(pc, ch.edge or ROOT, ch.cat):
                return False
            for g in ch.children:
                stack.append((g, ch.cat))
        return True


def evaluate_structured(sa: "StructuredModel", sb: "StructuredModel",
                        sentences: List[Sentence], n_samples: int = 200,
                        seed: int = 3) -> dict:
    rng = random.Random(seed)
    la = [sa.logp(s.root) for s in sentences]
    lb = [sb.logp(s.root) for s in sentences]
    ok = 0
    for _ in range(n_samples):
        if sa.conforms(sa.sample(rng)):
            ok += 1
    return {
        "avg_A": statistics.mean(la),
        "avg_B": statistics.mean(lb),
        "logZ_A": sa._logZ,
        "logZ_B": sb._logZ,
        "restriction_cost": sb._logZ - sa._logZ,
        "exp_size_A": sa._exp_size,
        "exp_size_B": sb._exp_size,
        "mu": sa.mu,
        "max_depth": sa.max_depth,
        "MC_conform_A": ok / n_samples,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_all() -> List[Sentence]:
    out: List[Sentence] = []
    for path in sorted(CGEL.glob("*.cgel")):
        out.extend(parse_cgel_file(str(path)))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CGEL treebank probability models")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--fit-b", action="store_true")
    ap.add_argument("--structured", action="store_true",
                    help="structural (generative) models A and B")
    ap.add_argument("--demo", metavar="SUBSTR", default=None)
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--iterations", type=int, default=150)
    args = ap.parse_args(argv)

    print("loading corpus...", flush=True)
    sentences = load_all()
    a = ModelA.fit(sentences, alpha=1.0)
    b = ModelB(a.p_cat, a.p_edge)   # restricted B: A's weights, B's support

    if args.structured:
        sta, stb = fit_structured(sentences, alpha=1.0)
        res = evaluate_structured(sta, stb, sentences, n_samples=args.samples)
        print("structural (generative) models -- whole tree, shape + labels")
        print(f"  mean arity mu = {res['mu']:.4f}  (sub-critical: {res['mu'] < 1})")
        print(f"  max depth bound = {res['max_depth']}")
        print(f"  expected tree size   A: {res['exp_size_A']:.1f}   "
              f"B: {res['exp_size_B']:.1f}")
        print(f"  log Z  A: {res['logZ_A']:.4f}  B: {res['logZ_B']:.4f}  "
              f"-> restriction cost log(Z_B/Z_A) = {res['restriction_cost']:.4f}")
        print(f"  avg log p(attested tree)   A: {res['avg_A']:.4f}   "
              f"B: {res['avg_B']:.4f}")
        print(f"  MC fraction of Model-A trees that conform (P_A): "
              f"{res['MC_conform_A']:.4f}")

    if args.eval:
        print("evaluating (exact DP + Monte Carlo conformity)...", flush=True)
        res = evaluate(sentences, a, b, n_samples=args.samples)
        print(f"sentences: {res['n']}")
        print(f"avg log p(attested)   Model A (independent labels): "
              f"{res['avg_logp_A']:.4f}")
        print(f"avg log p(attested)   Model B (conventions only):   "
              f"{res['avg_logp_B']:.4f}")
        print(f"avg log gain of B over A: {res['avg_log_gain']:.4f}")
        print("(Z_A = 1, so Z_B = P_A that a random labelling conforms;)")
        print(f"median Z_B:                {res['median_Z_B']:.8f}")
        print(f"median MC fraction of Model-A samples that conform: "
              f"{res['median_MC_conform_A']:.8f}")

    if args.fit_b:
        print(f"fitting log-linear Model B by MLE ({args.iterations} iters)...",
              flush=True)
        bf = fit_loglinear(sentences, iterations=args.iterations, verbose=True)
        print("evaluating...", flush=True)
        res = evaluate(sentences, a, bf, n_samples=args.samples)
        print(f"fitted B: avg log p(attested) = {res['avg_logp_B']:.4f} "
              f"(A: {res['avg_logp_A']:.4f}, gain {res['avg_log_gain']:.4f})")

    if args.demo:
        for s in sentences:
            if args.demo not in s.sent_id:
                continue
            sk = make_skeleton(s.root)
            print("\n" + "=" * 76)
            print("sent:", s.sent)
            a_best_cat = max(a.p_cat, key=a.p_cat.get)
            a_best_edge = max(a.p_edge, key=a.p_edge.get)
            a_map: Dict[Node, Tuple[str, str]] = {}
            for i, slot in enumerate(iter_slots(sk)):
                if slot.is_variable and slot.node is not None:
                    a_map[slot.node] = (a_best_cat, ROOT if i == 0 else a_best_edge)
            print("-- Model A (independent labels) MAP --")
            print(assignment_to_tree(sk, a_map).pretty())
            print(f"   p_A(MAP) = {a.prob(sk, a_map):.6g}")
            b_map = b.argmax(sk)
            print("-- Model B (conventions) MAP --")
            print(assignment_to_tree(sk, b_map).pretty())
            ba = attested_assignment(s)
            print(f"   p_B(MAP) = {b.prob(sk, b_map):.6g}   "
                  f"p_B(attested) = {b.prob(sk, ba):.6g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
