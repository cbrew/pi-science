"""Head-driven CGEL parser with coordination, markers and gap filling.

This extends the head-outward (Eisner-style) parser of ``cgel_headcyk.py``
with the devices proposed in ``docs/cgel-coordination-gaps.md``.  The
head-driven core is unchanged: a lexical head projects a category and takes
stopped left/right sequences of dependents.  Beside it sit two list schemas
that have no head and one feature that rides on every chart item.

    MARK    X  ->  Marker X              (Sdr marks a clause/VP; a
                                          Coordinator marks a conjunct)
    COORD   Coordination(X) -> X (MARK X)+   like conjuncts only
    SLASH   the categories of the material still missing below an item

A gap is a place where material found elsewhere in the sentence is needed:
the object of *operate* in *develop, build and operate -- this highway* is
the postposed NP; the head of the VP in *would this -- be fine* is the
fronted auxiliary.  The treebank writes this as a binder ``(x / NP ...)``
and a co-indexed ``(x / GAP)``, and ``Sentence.with_gaps_filled`` copies the
binder into the gap.  The parser's job is to deliver that link, so a gap is
a dependent **of the category of the material it stands for**: the token
``--`` enters the chart as ``GAP/NP``, ``GAP/V_aux``, ``GAP/AdvP`` ..., scored
by the ordinary dependent tables (``Obj: GAP/NP``, ``Mod: GAP/AdvP``, the
head slot ``GAP/V_aux -> Clause``), and the item above it carries ``/NP``,
``/V_aux``, ... until a binder of exactly that category is attached:

  * a ``Prenucleus``, ``Postnucleus`` or ``Head-Prenucleus`` dependent of
    category X discharges ``/X`` (the binder is itself gap-free);
  * a nominal head (``NP``/``Nom``) taking a clausal dependent that carries
    ``/Nom`` discharges it: the head noun is the material (relative clause);
  * a ``Coordination`` carries ``/X`` only if **every** conjunct carries
    ``/X`` (across the board): the one postposed NP fills every conjunct's
    gap;
  * a complete constituent may still be missing material (up to ``maxgap``
    categories) but never holds an unmatched binder; the root is missing
    nothing.

On output each binder is co-indexed with the gap(s) it fills, so the result
is a treebank-style tree: ``fill_gaps`` copies the material in and
``evaluate`` scores, for every gold gap, whether the parser copied the same
tokens into it.  Gap *positions* are taken from the input (the ``--``
tokens of the ``# sent`` line), so the chart stays token-indexed; see the
note for why that is the honest first step.

What the score is, and is not
-----------------------------
The chart maximises a product of locally normalised tables, each estimated
by relative frequency:

  * ``P(C | L)`` for every token: the category it projects, with ``<leaf>``
    (used as a bare dependent: a gap or a name piece) as one outcome;
  * ``P(stop | C, side)`` and ``P(f, D | C, side)`` for every head's two
    dependent sequences (``stop + sum dep = 1`` per side, which
    ``check_normalization`` verifies); a gap is one outcome ``(f, GAP/X)``;
  * ``P(X | marker word)``: which category a marker marks;
  * per coordination, a geometric number of extra conjuncts and, per
    non-initial conjunct, marked or bare.

That product is **not a probability distribution over analyses**, and the
tables are **not maximum-likelihood estimates of one**.  The gap discipline
(every open gap filled by a binder of its category, across the board
through coordination, nothing open at the root) and the like-category
requirement on conjuncts are hard constraints that rule analyses out, and
the local tables were normalised without them; the argument of Brew (1995,
*Stochastic HPSG*) and Abney (1997) applies exactly: with constraints, the
product of locally normalised, relative-frequency tables assigns mass to
analyses that do not exist, and the relative frequencies are not the
estimates that maximise the likelihood of the data under the constrained
model.  The same objection applies to a feature the core inherits from
``cgel_splithead``: a node's category is scored twice, by its parent's
emission ``P(f, D | C, side)`` and by its own projection ``P(D | L)``, two
overlapping local distributions whose product was never a distribution.

The model this *should* be is a conditional model over the chart's
analyses of the given string, ``P(tree | string) = exp(score) / Z(string)``,
with ``Z`` computed by an inside pass over the same chart (sum in place of
max) and the weights fitted to that normaliser (conditional maximum
likelihood by inside-outside expectations, as in Johnson et al. 1999), not
read off counts.  Until that is done, treat the numbers here as a scoring
function that happens to be built from relative frequencies: the Viterbi
parse is well defined, its score is not a probability, and the
``normalisation: OK`` line means only that each table sums to one.

Three further choices keep the output comparable to the treebank:

* **function labels are kept** in the emission tables, so every dependent
  carries its grammatical function and binders are identifiable;
* **unary head chains are folded** at extraction time (``Clause -> VP -> V``
  becomes one constituent headed by ``V`` with all the chain's dependents),
  and re-expanded on output with per-function attachment levels learnt from
  the corpus;
* how a marker token relates to the rest of the tree is **a modelling
  decision, not a given** (``markers=`` on the grammar; see the note):
    ``"schema"``     the marker is consumed by MARK; the governing head sees
                     a plain ``Clause``/``VP`` (the marker's information
                     stays inside its own constituent);
    ``"feature"``    as ``schema`` but the governing head sees the marked
                     category ``Clause[that]``, ``Clause[to]`` -- the
                     marker's information is shared with the governor;
    ``"dependent"``  the marker is an ordinary left dependent (``Marker``)
                     of the constituent's head in the split-head tables,
                     and a conjunct is any constituent beginning with a
                     Coordinator token.

Run:    python3 cgel_coordgap.py --eval        (self-fit + 5-fold CV; the
                                                headline is labelled
                                                attachment, LAS)
        python3 cgel_coordgap.py --ablate      (each device switched off)
        python3 cgel_coordgap.py --demo SUBSTR (parse, then gaps filled)
"""
from __future__ import annotations

import itertools
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cgel_headcyk import _brackets
from cgel_reader import Node, Sentence, _deepcopy, parse_cgel_file
from cgel_splithead import HEAD_EDGES, _dominant_child

CGEL = Path(__file__).resolve().parent / "cgel"
LOG0 = -math.inf
GAP = "GAP"
MARKERS = frozenset({"Sdr", "Coordinator"})
BINDERS = frozenset({"Prenucleus", "Postnucleus", "Head-Prenucleus"})
NOMINAL = frozenset({"NP", "Nom"})
CLAUSAL = frozenset({"Clause", "Clause_rel"})
ROOT_CATS = frozenset({"Clause", "Coordination", "NP", "VP", "Nom", "AdjP",
                       "PP", "AdvP", "IntP", "Clause_rel", "DP"})
MAXGAP = 2
NOGAPS: Tuple[str, ...] = ()
# functions a head takes at most once.  The treebank never repeats Subj,
# Det, Obj, Obj_ind, Obj_dir, PredComp, DisplacedSubj, ExtraposedSubj,
# Particle, Comp_ind, Postnucleus or Head-Prenucleus on a head (Comp and
# Prenucleus do repeat).  The chart tracks only the four that the parser
# ever repeated in practice: tracking all twelve multiplies the side keys
# (six times the run time on short sentences) and removes no further
# repeat.
ONCE = frozenset({"Subj", "Det", "Obj", "PredComp"})
# head classes that license a subject: finite verbs and auxiliaries, modals,
# and the inverted auxiliary's slot
FINITE = frozenset({"V:fin", "V_aux:fin", "V_aux:mod", GAP})


def gap_label(X: str) -> str:
    return f"{GAP}/{X}"


def is_gap_label(D: str) -> bool:
    return D.startswith(GAP + "/")


def binder_label(D: str) -> str:
    """The gap category a dependent of chart category ``D`` would supply as
    a binder: finiteness and marker features are not part of it."""
    D = D.split("[")[0]
    return "V_aux" if D.startswith("V_aux") else D


def binder_category(b: Node) -> str:
    """The category of the material a binder supplies.  A head noun binder
    (``N`` or ``Nom``) supplies a nominal; a coordinated binder supplies its
    conjuncts' category."""
    if b.cat in ("N", "Nom", "N_pro") or b.edge in HEAD_EDGES:
        return "Nom"                       # a nominal head, fused heads included
    if b.cat.startswith("V_aux"):
        return "V_aux"                     # finiteness is not part of the gap
    if b.cat == "Coordination":
        conj = [c for c in b.children if c.edge == "Coordinate"]
        return conj[0].cat if conj else b.cat
    return b.cat


# ---------------------------------------------------------------------------
# extraction: folded head chains, MARK events, COORD events
# ---------------------------------------------------------------------------

COMPLEMENT_TAKERS = {"N": "N_c", "Adj": "Adj_c"}


def relabel_complement_takers(root: Node) -> int:
    """Data intervention: a noun or adjective that takes a complement
    (``Comp``/``Comp_ind`` anywhere on its projection chain) gets the
    category ``N_c`` / ``Adj_c``, the way the treebank already separates
    ``V_aux`` from ``V``.  Valency then applies to those tokens and not to
    the ordinary majority (60 of 906 nouns, 14 of 221 adjectives).
    Returns the number of tokens relabelled."""
    parent = {c: n for n in root.iter_nodes() for c in n.children}
    done = 0
    for n in list(root.iter_nodes()):
        if n.cat not in COMPLEMENT_TAKERS or not n.is_lexical:
            continue
        top = _chain_top(n, parent)
        chain = head_chain(top)
        if not chain or chain[-1] is not n:
            continue
        if any(c.edge in ("Comp", "Comp_ind") for node in chain
               for c in node.children if c not in chain):
            n.cat = COMPLEMENT_TAKERS[n.cat]
            done += 1
    return done


FINITENESS = {"VBZ": "fin", "VBD": "fin", "VBP": "fin", "MD": "mod",
              "VB": "nonfin", "VBG": "nonfin", "VBN": "nonfin"}


def relabel_finiteness(root: Node) -> int:
    """Data intervention: verbs and auxiliaries carry their finiteness as
    part of the class, read off the Penn tag every one of them has:
    ``V:fin`` (VBZ, VBD, VBP), ``V:nonfin`` (VB, VBG, VBN), ``V_aux:mod``
    (MD), and likewise for ``V_aux``.  The subject attaches at the clause
    of the finite verb or auxiliary; this is what lets the chart license it
    there and nowhere else."""
    done = 0
    for n in root.iter_nodes():
        if n.cat in ("V", "V_aux") and n.is_lexical and n.pos in FINITENESS:
            n.cat = f"{n.cat}:{FINITENESS[n.pos]}"
            done += 1
    return done


def load_corpus(paths=None, finiteness: bool = True) -> List[Sentence]:
    """The treebank with the data interventions applied: complement-taking
    nouns and adjectives relabelled, and verb finiteness in the class."""
    paths = paths or sorted(CGEL.glob("*.cgel"))
    sents = [s for f in paths for s in parse_cgel_file(str(f))]
    for s in sents:
        relabel_complement_takers(s.root)
        if finiteness:
            relabel_finiteness(s.root)
    return sents


def leaf_positions(root: Node) -> Dict[Node, int]:
    """Surface position of every token, gaps included (matches ``# sent``)."""
    pos, i = {}, 0
    for n in root.iter_nodes():
        if n.is_lexical or n.is_gap or n.cat == GAP:
            pos[n] = i
            i += 1
    return pos


def _spans(root: Node, pos: Dict[Node, int]) -> Dict[Node, Tuple[int, int]]:
    spans = {}

    def span(n):
        if n in pos:
            lo = hi = pos[n]
            for c in n.children:          # Flat containers: N with N children
                a, b = span(c)
                lo, hi = min(lo, a), max(hi, b)
        else:
            lo, hi = 10 ** 9, -1
            for c in n.children:
                a, b = span(c)
                lo, hi = min(lo, a), max(hi, b)
        spans[n] = (lo, hi)
        return lo, hi
    span(root)
    return spans


def _is_head_child(n: Node) -> bool:
    return n.edge in HEAD_EDGES


def head_chain(top: Node) -> List[Node]:
    """``top`` down to its lexical (or GAP) head along head edges; the
    returned list is empty if the chain ends in a headless node."""
    chain, cur = [top], top
    while not (cur.is_lexical or cur.is_gap):
        d = _dominant_child(cur)
        if d is None and cur.children and all(
                c.edge == "Flat" and c.is_lexical for c in cur.children):
            d = cur.children[0]            # Flat container: first piece heads
        if d is None:
            return []
        chain.append(d)
        cur = d
    return chain


def _chain_top(n: Node, parent: Dict[Node, Node]) -> Node:
    while n in parent and _is_head_child(n):
        n = parent[n]
    return n


def _marker_word(c: Node) -> Optional[str]:
    """The Sdr marker word on ``c``'s head chain, if any (``feature`` mode)."""
    for node in head_chain(c) or [c]:
        for k in node.children:
            if k.edge == "Marker" and k.cat == "Sdr":
                return k.surface
    return None


def iter_events(s: Sentence, markers: str = "schema"):
    """Yield the derivational events of one tree.

    ``("proj", C, L, left, right, chain, levels)``: folded constituent of
        category ``C`` (the chain top), head POS ``L`` (``GAP/X`` for an
        inverted auxiliary's slot standing for an X); ``left``/``right`` are
        ``(f, D)`` dependents in surface order outward from the head, a gap
        dependent being ``GAP/X`` for the category X of its binder; ``chain``
        is the tuple of chain categories; ``levels`` maps ``(f, word-or-None)``
        to the chain category the dependent attaches at.
    ``("leaf", D)``: a bare token (gap or name piece) used as a dependent.
    ``("mark", kind, word, X, is_conjunct)``: a marker token marking the
        folded constituent of category ``X``.
    ``("coord", X, n, bare_nonfinal, ok)``: a coordination of ``n`` conjuncts
        of category ``X`` (first conjunct's category), ``bare_nonfinal`` the
        number of non-initial conjuncts without a marker, ``ok`` whether it
        is in the chart's support (like conjuncts, nothing else inside).
    ``("skip", C)``: a node that could not be folded (its head is a
        Coordination); it is reported, not modelled.

    ``markers`` selects how marker tokens enter the events (module doc).
    """
    pos = leaf_positions(s.root)
    spans = _spans(s.root, pos)
    parent = {}
    for n in s.root.iter_nodes():
        for c in n.children:
            parent[c] = n
    binders = {n.index: n for n in s.root.iter_nodes() if n.index and not n.is_gap}

    def dep_cat(c: Node) -> str:
        if c.is_gap:
            b = binders.get(c.index)
            return gap_label(binder_category(b) if b else "?")
        return c.cat

    for n in s.root.iter_nodes():
        if n.cat == "Coordination":
            conj = [c for c in n.children if c.edge == "Coordinate"]
            if len(conj) >= 2:
                bare = sum(1 for c in conj[1:]
                           if not any(k.edge == "Marker" for k in c.children))
                # in the chart's support only if the conjuncts share a
                # category and nothing but conjuncts is inside
                ok = (len({c.cat for c in conj}) == 1
                      and len(conj) == len(n.children))
                yield ("coord", conj[0].cat, len(conj), bare, ok)
            continue
        if n.edge == "Marker" and n.cat in MARKERS and n in parent:
            top = _chain_top(parent[n], parent)
            yield ("mark", n.cat, n.surface, top.cat, top.edge == "Coordinate")
            continue
        if (n in parent and _is_head_child(n)) or n.is_gap:
            continue                       # folded into its parent's chain
        if n.is_lexical and not n.children:
            continue
        if n.cat in MARKERS:
            continue
        chain = head_chain(n)
        if not chain:
            yield ("skip", n.cat)
            continue
        leaf = chain[-1]
        if leaf.cat in MARKERS:            # "etc." as Marker-Head: not modelled
            yield ("skip", n.cat)
            continue
        hp = pos[leaf]
        L = dep_cat(leaf) if leaf.is_gap else leaf.cat
        left, right, levels = [], [], {}
        for node in chain:
            for c in node.children:
                if c in chain:
                    continue
                if c.edge == "Marker" and c.cat in MARKERS:
                    levels[("Marker", c.surface)] = node.cat
                    if markers != "dependent":
                        continue
                D = dep_cat(c)
                if markers == "feature" and not c.is_lexical:
                    w = _marker_word(c)
                    if w:
                        D = f"{D}[{w}]"
                if c.is_gap or (c.is_lexical and not c.children and
                                (c.cat not in MARKERS or markers == "dependent")):
                    yield ("leaf", D)
                a, b = spans[c]
                (left if b < hp else right).append((pos[c] if c in pos else a,
                                                    (c.edge or "?", D)))
                if c.edge != "Marker":
                    levels[(c.edge or "?", None)] = node.cat
        left = [d for _, d in sorted(left, reverse=True)]   # outward
        right = [d for _, d in sorted(right)]
        yield ("proj", n.cat, L, tuple(left), tuple(right),
               tuple(x.cat if not x.is_gap else GAP for x in chain), levels)


# ---------------------------------------------------------------------------
# the grammar (tables)
# ---------------------------------------------------------------------------

def _smooth(counts: Counter, alpha: float) -> Dict:
    """Add-alpha over the observed support of a single distribution."""
    tot = sum(counts.values()) + alpha * len(counts)
    return {k: (v + alpha) / tot for k, v in counts.items()}


class Grammar:
    def __init__(self, sentences: Sequence[Sentence], alpha: float = 1.0,
                 markers: str = "schema"):
        assert markers in ("schema", "feature", "dependent"), markers
        self.markers = markers
        proj = defaultdict(Counter)        # L -> C   (incl. "<leaf>")
        dep = defaultdict(Counter)         # (C, side) -> (f, D) ; "" = stop
        mark = defaultdict(Counter)        # (kind, word) -> X
        mark_kind = defaultdict(Counter)   # kind -> X
        coord_cat = Counter()
        conj_total = conj_bare = ncoord = 0
        chains = defaultdict(Counter)      # (C, L) -> chain
        levels = defaultdict(Counter)      # (C, f, word|None) -> level cat
        self.skipped = Counter()
        for s in sentences:
            for ev in iter_events(s, markers):
                if ev[0] == "proj":
                    _, C, L, left, right, chain, lv = ev
                    proj[L][C] += 1
                    for side, seq in (("L", left), ("R", right)):
                        dep[(C, side)][""] += 1
                        for fd in seq:
                            dep[(C, side)][fd] += 1
                    chains[(C, L)][chain] += 1
                    for (f, w), cat in lv.items():
                        levels[(C, f, w)][cat] += 1
                elif ev[0] == "leaf":
                    proj[ev[1]]["<leaf>"] += 1
                elif ev[0] == "mark":
                    _, kind, word, X, _ = ev
                    mark[(kind, word)][X] += 1
                    mark_kind[kind][X] += 1
                elif ev[0] == "coord":
                    _, X, n, bare, _ok = ev
                    coord_cat[X] += 1
                    ncoord += 1
                    conj_total += n - 1
                    conj_bare += bare
                else:
                    self.skipped[ev[1]] += 1
        self.proj = {L: _smooth(c, alpha) for L, c in proj.items()}
        self.dep: Dict[Tuple[str, str], Dict] = {}
        self.stop: Dict[Tuple[str, str], float] = {}
        # dependents indexed by category for the chart: (C, side) -> D -> [(f, p)]
        self.emit: Dict[Tuple[str, str], Dict[str, List[Tuple[str, float]]]] = {}
        for key, c in dep.items():
            p = _smooth(c, alpha)
            self.stop[key] = p.pop("")
            self.dep[key] = p
            byD = defaultdict(list)
            for (f, D), v in p.items():
                byD[D].append((f, v))
            self.emit[key] = dict(byD)
        self.mark = {k: _smooth(c, alpha) for k, c in mark.items()}
        self.mark_kind = {k: _smooth(c, alpha) for k, c in mark_kind.items()}
        self.coord_cat = _smooth(coord_cat, alpha)
        self.p_more = (conj_total - ncoord + alpha) / (conj_total + 2 * alpha)
        self.p_bare = (conj_bare + alpha) / (conj_total + 2 * alpha)
        self.chain = {k: c.most_common(1)[0][0] for k, c in chains.items()}
        self.level = {k: c.most_common(1)[0][0] for k, c in levels.items()}
        self.cats = sorted({C for d in self.proj.values() for C in d
                            if C != "<leaf>"} | {"Coordination"})
        # the categories a gap may stand for (from the binders in the data)
        self.gapcats = sorted({L.split("/", 1)[1] for L in self.proj
                               if is_gap_label(L)})
        self.markable = {kind: set(d) for kind, d in self.mark_kind.items()}
        self.w = feature_weights(self)     # log-linear weights (§ Chart)

    def p_mark(self, kind: str, word: Optional[str], X: str) -> Optional[float]:
        d = self.mark.get((kind, word)) if word else None
        if d and X in d:
            return d[X]
        return self.mark_kind.get(kind, {}).get(X)

    def check_normalization(self) -> List[Tuple[str, str, float]]:
        return [(C, side, self.stop[(C, side)] + sum(self.dep[(C, side)].values()))
                for (C, side) in sorted(self.stop)]


def build_grammar(sentences, alpha: float = 1.0, markers: str = "schema") -> Grammar:
    return Grammar(sentences, alpha, markers)


# ---------------------------------------------------------------------------
# the chart
# ---------------------------------------------------------------------------

class Parse:
    def __init__(self, tree: Node, logp: float, root_cat: str):
        self.tree, self.logp, self.root_cat = tree, logp, root_cat
        self.brackets = _brackets(tree)


def _add(t: Tuple[str, ...], X: str) -> Tuple[str, ...]:
    return tuple(sorted(t + (X,)))


def _remove(t: Tuple[str, ...], X: str) -> Tuple[str, ...]:
    i = t.index(X)
    return t[:i] + t[i + 1:]


def _cancel(gaps: Tuple[str, ...], binders: Tuple[str, ...]):
    """Match pending binders against open gaps by category."""
    for X in binders:
        if X in gaps:
            gaps, binders = _remove(gaps, X), _remove(binders, X)
    return tuple(sorted(gaps)), binders


def feature_weights(g: "Grammar") -> Dict[tuple, float]:
    """The log-linear weights, initialised to the log relative frequencies of
    the tables (so the untrained model is the parser as before).  Features:
      ("proj", L, C)            head L projects C
      ("leaf", L)               bare token L used as a dependent
      ("stop", C, side)         end of a dependent sequence
      ("dep", C, side, f, D)    dependent (f, D) of a C head on that side
      ("mark", kind, word, X)   marker word marks X   (word-specific)
      ("markk", kind, X)        marker class marks X  (back-off)
      ("conj", "marked"|"bare") a non-initial conjunct with/without marker
      ("coord", "more"|"last")  another conjunct follows / the last one
    """
    lg = math.log
    w: Dict[tuple, float] = {}
    for L, d in g.proj.items():
        for C, p in d.items():
            w[("leaf", L) if C == "<leaf>" else ("proj", L, C)] = lg(p)
    for (C, side), p in g.stop.items():
        w[("stop", C, side)] = lg(p)
    for (C, side), d in g.dep.items():
        for (f, D), p in d.items():
            w[("dep", C, side, f, D)] = lg(p)
    for (kind, word), d in g.mark.items():
        for X, p in d.items():
            w[("mark", kind, word, X)] = lg(p)
    for kind, d in g.mark_kind.items():
        for X, p in d.items():
            w[("markk", kind, X)] = lg(p)
    w[("conj", "marked")] = lg(1 - g.p_bare)
    w[("conj", "bare")] = lg(g.p_bare)
    w[("coord", "more")] = lg(g.p_more)
    w[("coord", "last")] = lg(1 - g.p_more)
    return w


class Chart:
    """The chart, driven by one of two semirings over the same rule loops.

    ``mode="max"`` is Viterbi: each cell key holds ``(score, backpointer)``.
    ``mode="sum"`` is the inside pass: each key holds ``(log inside mass,
    None)`` and, with ``record=True``, every edge is kept as ``(head cell,
    head key, [(tail cell, tail key), ...], features)`` in creation order
    for the outside pass.  The support (which keys exist) is the same in
    both modes; the weight of an edge is the sum of its features' weights.
    """

    def __init__(self, g: "Grammar", ts: Sequence[str],
                 words: Optional[Sequence[str]] = None, maxgap: int = MAXGAP,
                 coord: bool = True, slash: bool = True, mode: str = "max",
                 record: bool = False, once: bool = True, finite: bool = True):
        self.g, self.ts = g, list(ts)
        self.once, self.finite = once, finite
        self.n = len(self.ts)
        self.words = list(words) if words else [None] * self.n
        self.maxgap, self.coord, self.slash = maxgap, coord, slash
        self.mode, self.record = mode, record
        self.w = g.w
        N1 = self.n + 1
        self.left = [[{} for _ in range(N1)] for _ in range(N1)]
        self.right = [[{} for _ in range(N1)] for _ in range(N1)]
        self.arg = [[{} for _ in range(N1)] for _ in range(N1)]
        self.conj = [[{} for _ in range(N1)] for _ in range(N1)]
        self.tail = [[{} for _ in range(N1)] for _ in range(N1)]
        self.edges: list = []
        self.roots: list = []

    # -- the semiring ------------------------------------------------------
    def edge(self, cell: dict, key, tails, feats, bp) -> None:
        val = 0.0
        for tcell, tkey in tails:
            val += tcell[tkey][0]
        for f in feats:
            val += self.w[f]
        cur = cell.get(key)
        if self.mode == "max":
            if cur is None or val > cur[0]:
                cell[key] = (val, bp)
        else:
            cell[key] = (val if cur is None else _logaddexp(cur[0], val), None)
        if self.record:
            self.edges.append((cell, key, tails, feats))

    def mark_feature(self, kind: str, word: Optional[str], X: str):
        f = ("mark", kind, word, X)
        if f in self.w:
            return f
        f = ("markk", kind, X)
        return f if f in self.w else None

    # -- the rules ---------------------------------------------------------
    def run(self) -> "Chart":
        g, ts, words, n = self.g, self.ts, self.words, self.n
        maxgap, slash = self.maxgap, self.slash
        left, right, arg, conj, tail = \
            self.left, self.right, self.arg, self.conj, self.tail
        edge = self.edge
        W = self.w

        def attach(C, side, cell, m, inner, D_cell, h):
            """Extend a left/right chain by one dependent constituent of the
            head at token ``h``."""
            emit = g.emit.get((C, side))
            if not emit:
                return
            head_class = ts[h]
            for dkey, _dv in D_cell.items():
                D, gd, _bd = dkey
                fs = emit.get(D)
                if not fs:
                    continue
                for ikey in inner:
                    C0, g0, b0, used0 = ikey
                    if C0 != C:
                        continue
                    for f, _p in fs:
                        if self.once and f in ONCE and f in used0:
                            continue                      # at most once per head
                        if self.finite and f == "Subj" and head_class not in FINITE:
                            continue                      # a finite head licenses it
                        gaps, binders = g0 + gd, b0
                        if f in BINDERS:
                            if gd:                        # a binder is gap-free
                                continue
                            X = binder_label(D)
                            if X in gaps:
                                gaps = _remove(gaps, X)   # fills a gap below
                            else:
                                binders = _add(binders, X)  # gap on the other side
                        elif C in NOMINAL and D.split("[")[0] in CLAUSAL and "Nom" in gd:
                            gaps = _remove(gaps, "Nom")   # the head noun is the material
                        gaps = tuple(sorted(gaps))
                        if not slash:
                            gaps, binders = NOGAPS, NOGAPS
                        if len(gaps) > maxgap or len(binders) > maxgap:
                            continue
                        used = tuple(sorted(used0 + (f,))) \
                            if (self.once and f in ONCE) else used0
                        edge(cell, (C, gaps, binders, used),
                             [(inner, ikey), (D_cell, dkey)],
                             [("dep", C, side, f, D)], (m, dkey, f, ikey))

        # heads: base cells (F = 0)
        for h in range(n):
            for L in ([gap_label(X) for X in g.gapcats] if ts[h] == GAP else [ts[h]]):
                if L in MARKERS:
                    continue
                for C in g.proj.get(L, {}):
                    if C == "<leaf>":
                        continue
                    if ("stop", C, "L") not in W or ("stop", C, "R") not in W:
                        continue
                    g0 = (L.split("/", 1)[1],) if (ts[h] == GAP and slash) else NOGAPS
                    edge(left[h][h], (C, g0, NOGAPS, ()), [],
                         [("proj", L, C), ("stop", C, "L")], ("base", L))
                    edge(right[h][h + 1], (C, NOGAPS, NOGAPS, ()), [],
                         [("stop", C, "R")], "stop")

        for F in range(1, n + 1):
            # ---- complete constituents over [i, k) --------------------------
            for i in range(0, n - F + 1):
                k = i + F
                cell = arg[i][k]
                if F == 1:
                    if ts[i] == GAP:
                        for X in g.gapcats:
                            if ("leaf", gap_label(X)) in W:
                                gx = (X,) if slash else NOGAPS
                                edge(cell, (gap_label(X), gx, NOGAPS), [],
                                     [("leaf", gap_label(X))], ("leaf", X))
                    elif ("leaf", ts[i]) in W:                   # a Flat name piece
                        edge(cell, (ts[i], NOGAPS, NOGAPS), [],
                             [("leaf", ts[i])], ("leaf", None))
                for h in range(i, k):
                    for lkey in left[i][h]:
                        C, gl, bl, frl = lkey
                        for rkey in right[h][k]:
                            if rkey[0] != C:
                                continue
                            gaps, binders = _cancel(gl + rkey[1], bl + rkey[2])
                            if binders or len(gaps) > maxgap:
                                continue
                            if set(frl) & set(rkey[3]):
                                continue              # once-only on both sides
                            edge(cell, (C, gaps, NOGAPS),
                                 [(left[i][h], lkey), (right[h][k], rkey)], [],
                                 ("head", h, lkey, rkey))
                if ts[i] == "Sdr" and F >= 2 and g.markers != "dependent":
                    for (X, gx, _b) in list(arg[i + 1][k]):
                        mf = self.mark_feature("Sdr", words[i], X)
                        if mf:
                            Xm = f"{X}[{words[i]}]" if g.markers == "feature" else X
                            edge(cell, (Xm, gx, NOGAPS),
                                 [(arg[i + 1][k], (X, gx, _b))], [mf], ("mark", X, gx))
                for m in range(i + 1, k) if self.coord else ():
                    for key in arg[i][m]:
                        if key in tail[m][k] and key[0].split("[")[0] in g.coord_cat:
                            edge(cell, ("Coordination", key[1], NOGAPS),
                                 [(arg[i][m], key), (tail[m][k], key)], [],
                                 ("coord", m, key))
            # ---- marked conjuncts and conjunct tails ------------------------
            for i in range(0, n - F + 1):
                k = i + F
                if ts[i] == "Coordinator" and F >= 2:
                    if g.markers == "dependent":      # marker already inside arg
                        for key in list(arg[i][k]):
                            edge(conj[i][k], key, [(arg[i][k], key)],
                                 [("conj", "marked")], ("conj-arg",))
                    else:
                        for key in list(arg[i + 1][k]):
                            mf = self.mark_feature("Coordinator", words[i], key[0])
                            if mf:
                                edge(conj[i][k], key, [(arg[i + 1][k], key)],
                                     [mf, ("conj", "marked")], ("conj", key))
                tcell = tail[i][k]
                for key in list(conj[i][k]):
                    edge(tcell, key, [(conj[i][k], key)], [("coord", "last")], ("last",))
                for m in range(i + 1, k):
                    for key in tail[m][k]:
                        if key in conj[i][m]:
                            edge(tcell, key, [(conj[i][m], key), (tail[m][k], key)],
                                 [("coord", "more")], ("more", m, "conj"))
                        if key in arg[i][m] and key[0] != "Coordination":
                            edge(tcell, key, [(arg[i][m], key), (tail[m][k], key)],
                                 [("conj", "bare"), ("coord", "more")], ("more", m, "arg"))
            # ---- left chains: head at h = i + F -----------------------------
            for i in range(0, n - F):
                h = i + F
                for m in range(i + 1, h + 1):
                    if arg[i][m] and left[m][h]:
                        for C in {C0 for (C0, _, _, _) in left[m][h]}:
                            attach(C, "L", left[i][h], m, left[m][h], arg[i][m], h)
            # ---- right chains: head at h, dependents over (h, h + F] --------
            for h in range(0, n - F):
                k = h + F + 1
                for m in range(h + 1, k):
                    if arg[m][k] and right[h][m]:
                        for C in {C0 for (C0, _, _, _) in right[h][m]}:
                            attach(C, "R", right[h][k], m, right[h][m], arg[m][k], h)

        for key in arg[0][n]:
            C, gaps, _b = key
            if not gaps and C.split("[")[0] in ROOT_CATS:
                self.roots.append((arg[0][n], key, "arg"))
        if g.markers != "dependent":
            for key in conj[0][n]:                      # clause-initial "and"
                C, gaps, _b = key
                if not gaps and C in ROOT_CATS:
                    self.roots.append((conj[0][n], key, "conj"))
        return self

    def log_inside(self) -> float:
        """log Z(string): the total mass of all analyses (mode "sum")."""
        vals = [cell[key][0] for cell, key, _ in self.roots]
        if not vals:
            return LOG0
        m = max(vals)
        return m + math.log(sum(math.exp(v - m) for v in vals))


def _logaddexp(a: float, b: float) -> float:
    if a == LOG0:
        return b
    if b == LOG0:
        return a
    m = max(a, b)
    return m + math.log1p(math.exp(-abs(a - b)))


def parse(g: Grammar, ts: Sequence[str], words: Optional[Sequence[str]] = None,
          maxgap: int = MAXGAP, coord: bool = True, slash: bool = True,
          once: bool = True, finite: bool = True) -> Optional[Parse]:
    """Viterbi parse of a lexical-category sequence (``GAP`` tokens included).

    ``coord=False`` switches the COORD schema off, ``slash=False`` the gap
    feature (gaps are then tokens with no binding discipline), ``once=False``
    the at-most-once rule for the functions the treebank never repeats on a
    head, and ``finite=False`` the licensing of a subject by a finite head;
    all exist for ablation.  See ``Chart`` for the cells and keys.
    """
    if len(ts) == 0:
        return None
    ch = Chart(g, ts, words, maxgap, coord, slash, mode="max",
               once=once, finite=finite).run()
    best, bkey, bcell, bkind = LOG0, None, None, None
    for cell, key, kind in ch.roots:
        if cell[key][0] > best:
            best, bkey, bcell, bkind = cell[key][0], key, cell, kind
    if bkey is None:
        return None
    tree = _Rebuilder(g, ch.ts, ch.words, ch.left, ch.right, ch.arg, ch.conj,
                      ch.tail).build(bkind, 0, ch.n, bkey)
    tree.edge = None
    link_gaps(tree)
    return Parse(tree, best, tree.cat)


class _Rebuilder:
    def __init__(self, g, ts, words, left, right, arg, conj, tail):
        self.g, self.ts, self.words = g, ts, words
        self.left, self.right, self.arg, self.conj, self.tail = \
            left, right, arg, conj, tail

    def leaf(self, i: int, X: Optional[str] = None) -> Node:
        if self.ts[i] == GAP:
            return Node(cat=GAP, feats={"for": [X or "?"]})
        return Node(cat=self.ts[i], feats={"t": [self.words[i] or self.ts[i]]})

    def build(self, kind: str, i: int, k: int, key) -> Node:
        if kind == "conj":
            _, bp = self.conj[i][k][key]
            if bp[0] == "conj-arg":
                return self.build("arg", i, k, key)
            body = self.build("arg", i + 1, k, bp[1])
            marker = self.leaf(i)
            marker.edge = "Marker"
            body.edge = "Head"
            return Node(cat=key[0], children=[marker, body])
        _, bp = self.arg[i][k][key]
        if bp[0] == "leaf":
            return self.leaf(i, bp[1])
        if bp[0] == "mark":
            _, X, gx = bp
            body = self.build("arg", i + 1, k, (X, gx, NOGAPS))
            marker = self.leaf(i)
            marker.edge = "Marker"
            return self.expand_marked(X, marker, body)
        if bp[0] == "coord":
            _, m, ckey = bp
            first = self.build("arg", i, m, ckey)
            first.edge = "Coordinate"
            return Node(cat="Coordination",
                        children=[first] + self.build_tail(m, k, ckey))
        _, h, lkey, rkey = bp
        C = key[0]
        deps_l = self.chain_deps("L", i, h, lkey)
        deps_r = self.chain_deps("R", h, k, rkey)
        base = self.left[h][h][self._base_key(i, h, lkey)][1]
        return self.expand(C, h, base[1], deps_l, deps_r)

    def _base_key(self, i, h, key):
        while i != h:
            _, bp = self.left[i][h][key]
            i, key = bp[0], bp[3]
        return key

    def build_tail(self, m: int, k: int, key) -> List[Node]:
        _, bp = self.tail[m][k][key]
        if bp[0] == "last":
            c = self.build("conj", m, k, key)
            c.edge = "Coordinate"
            return [c]
        _, m2, kind = bp
        c = self.build(kind, m, m2, key)
        c.edge = "Coordinate"
        return [c] + self.build_tail(m2, k, key)

    def chain_deps(self, side: str, a: int, b: int, key) -> List[Tuple[str, Node]]:
        """Dependents (function, node) of one side in surface order."""
        out = []
        if side == "L":
            i, h = a, b
            while i != h:
                _, bp = self.left[i][h][key]
                m, dkey, f, ikey = bp
                node = self.build("arg", i, m, dkey)
                node.edge = f
                out.append((f, node))
                i, key = m, ikey
            return out
        h, k = a, b
        while k != h + 1:
            _, bp = self.right[h][k][key]
            m, dkey, f, ikey = bp
            node = self.build("arg", m, k, dkey)
            node.edge = f
            out.append((f, node))
            k, key = m, ikey
        return list(reversed(out))

    # -- unary re-expansion ---------------------------------------------------
    def expand(self, C: str, h: int, L: str, deps_l, deps_r) -> Node:
        chain = list(self.g.chain.get((C, L), (C, L)))
        depth = {}                                        # 0 = top
        for d, cat in enumerate(chain):
            depth.setdefault(cat, d)
        bottom = len(chain) - 1

        def lvl(f, node):
            w = node.surface if f == "Marker" else None
            cat = self.g.level.get((C, f, w))
            return depth.get(cat, 0)
        # outward-monotone attachment: a dependent further from the head
        # can never attach lower than one nearer to it
        def assign(deps_in_to_out):
            out, cur = [], bottom
            for f, node in deps_in_to_out:
                cur = min(cur, lvl(f, node))
                out.append((cur, node))
            return out
        lv_l = assign(list(reversed(deps_l)))         # nearest the head first
        lv_r = assign(deps_r)
        head = self.leaf(h, L.split("/", 1)[1] if is_gap_label(L) else None)
        head.edge = "Head"
        node = head
        for d in range(bottom, -1, -1):
            kids_l = [nd for (lv, nd) in reversed(lv_l) if lv == d]
            kids_r = [nd for (lv, nd) in lv_r if lv == d]
            if d == bottom:
                node.children = kids_l + list(node.children) + kids_r
                continue
            node = Node(cat=chain[d], edge="Head", children=kids_l + [node] + kids_r)
        return node

    def expand_marked(self, X: str, marker: Node, body: Node) -> Node:
        """Put the marker at its learnt level inside ``body`` (a folded
        constituent of category X): ``Clause -> VP(:Marker to :Head VP)``."""
        target = self.g.level.get((X, "Marker", marker.surface)) or X
        node = body
        while node.cat != target:
            heads = [c for c in node.children if c.edge == "Head" and not c.is_lexical]
            if not heads:
                break
            node = heads[0]
        if node.cat != target:
            node = body
        node.children.insert(0, marker)
        return body


# ---------------------------------------------------------------------------
# gap linking and filling
# ---------------------------------------------------------------------------

def link_gaps(tree: Node) -> int:
    """Co-index every binder with the gap(s) it fills, using the same rules
    as the chart: a Prenucleus/Postnucleus/Head-Prenucleus child of category
    X fills an open X gap in its sisters; the head of a nominal fills an
    open Nom gap in a clausal sister; a Coordination merges its conjuncts'
    gaps of the same category into one.  Returns the number of indices."""
    counter = [0]

    def fresh():
        counter[0] += 1
        return f"g{counter[0]}"

    def bind(open_gaps: List[Tuple[str, List[Node]]], X: str, binder: Node) -> bool:
        for j, (cat, nodes) in enumerate(open_gaps):
            if cat == X:
                ix = fresh()
                binder.index = ix
                for gnode in nodes:
                    gnode.index = ix
                del open_gaps[j]
                return True
        return False

    def walk(n: Node) -> List[Tuple[str, List[Node]]]:
        if n.cat == GAP:
            return [(n.get("for", "?"), [n])]
        if n.cat == "Coordination":
            merged: Dict[str, List[Node]] = {}
            for c in n.children:
                for cat, nodes in walk(c):
                    merged.setdefault(cat, []).extend(nodes)
            return [(cat, nodes) for cat, nodes in merged.items()]
        below: List[Tuple[str, List[Node]]] = []
        per_child = [(c, walk(c)) for c in n.children]
        for c, og in per_child:
            below.extend(og)
        for c, _ in per_child:
            if c.edge in BINDERS:
                bind(below, binder_label(c.cat), c)
        if n.cat in NOMINAL:
            heads = [c for c in n.children if c.edge == "Head"]
            if heads and any(c.cat.split("[")[0] in CLAUSAL for c, _ in per_child):
                bind(below, "Nom", heads[0])
        return below
    walk(tree)
    return counter[0]


def fill_gaps(tree: Node) -> Node:
    """Copy of ``tree`` with every indexed gap replaced by a copy of its
    binder (what ``Sentence.with_gaps_filled`` does for treebank trees)."""
    bind = {n.index: n for n in tree.iter_nodes() if n.index and n.cat != GAP}

    def fill(n: Node) -> Node:
        if n.cat == GAP and n.index in bind:
            clone = fill(_deepcopy(bind[n.index]))
            clone.index = None
            clone.edge = n.edge
            return clone
        return Node(cat=n.cat, index=n.index, edge=n.edge,
                    feats={k: list(v) for k, v in n.feats.items()},
                    children=[fill(c) for c in n.children])
    return fill(tree)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

def sentence_tokens(s: Sentence) -> List[str]:
    return [GAP if n.is_gap else n.cat for n in s.root.iter_nodes()
            if n.is_lexical or n.is_gap]


def sentence_words(s: Sentence) -> List[Optional[str]]:
    return [n.surface for n in s.root.iter_nodes() if n.is_lexical or n.is_gap]


def _kind(s: Sentence) -> str:
    cats = {n.cat for n in s.root.iter_nodes()}
    return "+".join(k for k, c in (("coord", "Coordination"), ("gap", GAP),
                                   ("sdr", "Sdr")) if c in cats) or "plain"


def gap_bindings(root: Node) -> List[Tuple[int, Optional[Tuple[int, int]]]]:
    """For every gap in surface order: (its token position, the token span
    of the material bound to it, or None if unbound)."""
    pos = leaf_positions(root)
    spans = _spans(root, pos)
    binders = {n.index: n for n in root.iter_nodes() if n.index and n.cat != GAP}
    out = []
    for n in root.iter_nodes():
        if n.cat == GAP:
            b = binders.get(n.index)
            out.append((pos[n], spans[b] if b is not None else None))
    return out


def head_token(n: Node, pos: Dict[Node, int]) -> Optional[int]:
    """The token that heads ``n``: down the head chain (a Flat container to
    its first piece); a Coordination to its first conjunct's head; None for
    a headless node."""
    while n not in pos:
        if n.cat == "Coordination":
            conj = [c for c in n.children if c.edge == "Coordinate"]
            if not conj:
                return None
            n = conj[0]
            continue
        d = _dominant_child(n)
        if d is None and n.children and all(
                c.edge == "Flat" and c.is_lexical for c in n.children):
            d = n.children[0]
        if d is None:
            return None
        n = d                       # one step: a Coordination head is followed too
    return pos[n]


def dependencies(root: Node) -> Dict[int, Tuple[int, str]]:
    """Labelled dependencies read off a headed tree: token -> (head token,
    function).  A token depends on the head of the parent of the highest
    constituent it heads, with that constituent's function label; a marker
    depends on the head of what it marks (``Marker``); a non-initial
    conjunct on the first conjunct's head (``Coordinate``); a gap token is
    a token like any other.  The root token has no entry.  Applied alike to
    gold and parsed trees, so the two sides are converted the same way."""
    pos = leaf_positions(root)
    out: Dict[int, Tuple[int, str]] = {}

    def walk(n: Node) -> None:
        h = head_token(n, pos)
        for c in n.children:
            ch = head_token(c, pos)
            if ch is not None and h is not None and ch != h:
                out[ch] = (h, c.edge or "?")
            walk(c)
    walk(root)
    return out


def collapsed_brackets(root: Node) -> Dict[Tuple[int, int], set]:
    """span -> set of labels: a unary chain over one span counts once."""
    d: Dict[Tuple[int, int], set] = defaultdict(set)
    for cat, sp in _brackets(root):
        d[sp].add(cat)
    return d


def _gap_sites(root: Node) -> List[Tuple[str, str]]:
    parent = {c: n for n in root.iter_nodes() for c in n.children}
    return [(n.edge or "?", parent[n].cat) for n in root.iter_nodes()
            if n.cat == GAP]


def evaluate(sentences, g: Grammar, maxgap: int = MAXGAP, **sw) -> list:
    rows = []
    for s in sentences:
        gold = _brackets(s.root)
        pr = parse(g, sentence_tokens(s), sentence_words(s), maxgap, **sw)
        row = {"id": s.sent_id, "kind": _kind(s), "parsed": pr is not None}
        if pr is not None:
            row["root"] = pr.root_cat == s.root.cat
            gd, pd = dependencies(s.root), dependencies(pr.tree)
            row["dep_n"] = len(gd)
            row["uas"] = sum(1 for t, (h, _) in gd.items()
                             if t in pd and pd[t][0] == h)
            row["las"] = sum(1 for t, hf in gd.items() if pd.get(t) == hf)
            row["exact"] = row["las"] == len(gd)
            gc_, pc_ = collapsed_brackets(s.root), collapsed_brackets(pr.tree)
            hit = sum(1 for sp in pc_ if sp in gc_ and pc_[sp] & gc_[sp])
            row["col_pred"], row["col_gold"], row["col_hit"] = len(pc_), len(gc_), hit
            gc = {b for b in gold if b[0] == "Coordination"}
            row["coord_gold"] = len(gc)
            row["coord_hit"] = len(gc & pr.brackets)
            gb, pb = gap_bindings(s.root), gap_bindings(pr.tree)
            row["gap_gold"] = len(gb)
            row["gap_filled"] = sum(1 for (_, a), (_, b) in zip(gb, pb)
                                    if a is not None and a == b)
            gs, ps = _gap_sites(s.root), _gap_sites(pr.tree)
            row["gap_parent"] = sum(1 for a, b in zip(gs, ps) if a[1] == b[1])
        rows.append(row)
    return rows


def summarize(rows, label: str) -> str:
    ok = [r for r in rows if r["parsed"]]
    dn = sum(r.get("dep_n", 0) for r in ok)
    las = sum(r.get("las", 0) for r in ok) / dn if dn else 0.0
    uas = sum(r.get("uas", 0) for r in ok) / dn if dn else 0.0
    cp = sum(r.get("col_pred", 0) for r in ok)
    cg_ = sum(r.get("col_gold", 0) for r in ok)
    chh = sum(r.get("col_hit", 0) for r in ok)
    cpr, crc = (chh / cp if cp else 0.0), (chh / cg_ if cg_ else 0.0)
    colf1 = 2 * cpr * crc / (cpr + crc) if cpr + crc else 0.0
    cg = sum(r.get("coord_gold", 0) for r in ok)
    ch = sum(r.get("coord_hit", 0) for r in ok)
    gg = sum(r.get("gap_gold", 0) for r in ok)
    gf = sum(r.get("gap_filled", 0) for r in ok)
    gp = sum(r.get("gap_parent", 0) for r in ok)
    out = [f"{label}: parsed={len(ok)}/{len(rows)}  "
           f"LAS={las:.3f}  UAS={uas:.3f}  collapsed-bracket-F1={colf1:.3f}  "
           f"coordination-brackets={ch}/{cg}  "
           f"gaps filled with the gold material={gf}/{gg}  "
           f"all-dependencies-right={sum(r['exact'] for r in ok)}  "
           f"root-match={sum(r['root'] for r in ok)}/{len(ok)}"]
    by = defaultdict(list)
    for r in ok:
        by[r["kind"]].append(r)
    allk = Counter(r["kind"] for r in rows)
    for k in sorted(allk):
        v = by.get(k, [])
        n_ = sum(r.get("dep_n", 0) for r in v)
        l_ = sum(r.get("las", 0) for r in v) / n_ if n_ else 0.0
        out.append(f"    {k:16s} parsed {len(v):3d}/{allk[k]:3d}  LAS={l_:.3f}")
    return "\n".join(out)


def cross_validate(sentences, folds: int = 5, seed: int = 0, alpha: float = 1.0,
                   maxgap: int = MAXGAP, label: str = "",
                   markers: str = "schema", **sw) -> str:
    rng = random.Random(seed)
    order = list(sentences)
    rng.shuffle(order)
    size = (len(order) + folds - 1) // folds
    rows = []
    for fold in range(folds):
        test = order[fold * size:(fold + 1) * size]
        train = [s for s in order if s not in test]
        rows += evaluate(test, build_grammar(train, alpha, markers), maxgap, **sw)
    return summarize(rows, f"{folds}-fold CV, {label or 'coordination+gaps'}")


def render(n: Node) -> str:
    e = f":{n.edge} " if n.edge else ""
    ix = f"{n.index} / " if n.index else ""
    if n.cat == GAP:
        return f"{e}({ix}GAP)"
    if n.is_lexical and not n.children:
        return f"{e}({ix}{n.cat} {n.surface})"
    return f"{e}({ix}{n.cat} {' '.join(render(c) for c in n.children)})"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--demo", metavar="SUBSTR", default="")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--maxgap", type=int, default=MAXGAP)
    ap.add_argument("--markers", default="schema",
                    choices=["schema", "feature", "dependent"])
    ap.add_argument("--ablate", action="store_true",
                    help="CV with COORD off / SLASH off / maxgap=1 / marker modes")
    args = ap.parse_args()
    sentences = load_corpus()
    if args.eval:
        g = build_grammar(sentences, args.alpha, args.markers)
        bad = [(C, sd, t) for C, sd, t in g.check_normalization() if abs(t - 1) > 1e-9]
        print(f"per-table normalisation (stop + sum dep per side): "
              f"{'OK' if not bad else bad}   gap categories: "
              f"{g.gapcats}   unfolded (Coordination-headed) nodes skipped: "
              f"{dict(g.skipped)}")
        print(summarize(evaluate(sentences, g, args.maxgap), "self-fit"))
        print(cross_validate(sentences, args.folds, alpha=args.alpha,
                             maxgap=args.maxgap, markers=args.markers))
    if args.ablate:
        for label, kw in (("COORD off", dict(coord=False)),
                          ("SLASH off", dict(slash=False)),
                          ("ONCE off", dict(once=False)),
                          ("FINITE off", dict(finite=False)),
                          ("maxgap=1", dict(maxgap=1)),
                          ("markers=feature", dict(markers="feature")),
                          ("markers=dependent", dict(markers="dependent"))):
            print(cross_validate(sentences, args.folds, alpha=args.alpha,
                                 label=label,
                                 **({"maxgap": MAXGAP} | kw)).split("\n")[0])
    if args.demo:
        g = build_grammar(sentences, args.alpha, args.markers)
        for s in sentences:
            if args.demo not in s.sent:
                continue
            pr = parse(g, sentence_tokens(s), sentence_words(s), args.maxgap)
            print("\nsent:", s.sent)
            print("yield:", " ".join(sentence_tokens(s)))
            if pr is None:
                print("  (no parse)")
            else:
                gd, pd = dependencies(s.root), dependencies(pr.tree)
                las = sum(1 for t, hf in gd.items() if pd.get(t) == hf)
                print(f"  root={pr.root_cat}  score={pr.logp:.3f}  "
                      f"LAS={las}/{len(gd)}")
                print("  parse:  " + render(pr.tree))
                print("  filled: " + render(fill_gaps(pr.tree)))
                print("  gold:   " + render(s.root))
            break


if __name__ == "__main__":
    main()
