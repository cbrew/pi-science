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

import heapq
import itertools
import math
import random
import statistics
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Tuple

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
ROOT_CATS = frozenset({"Clause", "Coordination", "NP", "VP", "Nom", "AdjP"})
# the categories a tree may be rooted in: the six observed in the treebank
# (Clause 167, Coordination 34, NP 16, VP, Nom, AdjP once each)
MAXGAP = 2
# evaluation length bound: sentences longer than this are not parsed and are
# reported as excluded.  The chart's gap-binder state product makes the two
# longest sentences (34 and 36 tokens) infeasible; the author chose to keep
# two open gaps (the wh-question-plus-inversion construction) and exclude
# those two sentences until the chart is rebuilt (design document §9).
MAXTOK = 32
NOGAPS: Tuple[str, ...] = ()
# functions a head takes at most once.  The treebank never repeats Subj,
# Det, Obj, Obj_ind, Obj_dir, PredComp, DisplacedSubj, ExtraposedSubj,
# Particle, Comp_ind, Postnucleus or Head-Prenucleus on a head (Comp and
# Prenucleus do repeat).  The chart tracks the four the parser repeated in
# practice, plus the two binder functions: a second Postnucleus or
# Head-Prenucleus never occurs, and excluding it bounds the pending
# binders a right chain can carry (344,000 keys instead of 456,000 on the
# 32-token right-node-raising sentence).  Tracking all twelve multiplied
# the keys for no further effect.
ONCE = frozenset({"Subj", "Det", "Obj", "PredComp", "Postnucleus", "Head-Prenucleus"})
# head classes that license a subject: finite verbs and auxiliaries, modals,
# and the inverted auxiliary's slot
FINITE = frozenset({"V:fin", "V_aux:fin", "V_aux:mod", GAP})
# complement functions: licensed by the head's class (CGEL ch. 4 §1.2: a
# complement "require[s] the presence of an appropriate verb that licenses
# it"); the licensing set is read off the treebank per class
COMPLEMENT = frozenset({"Obj", "Obj_ind", "Obj_dir", "Comp", "Comp_ind",
                        "PredComp", "Particle", "DisplacedSubj", "ExtraposedSubj",
                        "Obj+Mod", "Obj+PredComp/Comp"})


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
                ok = len(conj) == len(n.children)     # CGEL: like function, not category
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
        self.licensed: set = set()          # (head class, complement function)
        self.slots: Dict[tuple, set] = {}   # (C, side, f) -> categories licensed there
        for s in sentences:
            for ev in iter_events(s, markers):
                if ev[0] == "proj":
                    _, C, L, left, right, chain, lv = ev
                    proj[L][C] += 1
                    for f, _D in left + right:
                        if f in COMPLEMENT:
                            self.licensed.add((L, f))
                            if is_gap_label(L):          # the chart sees the slot as GAP
                                self.licensed.add((GAP, f))
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
            for (f, D) in p:
                self.slots.setdefault(key + (f,), set()).add(D)
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
        self.gapset = frozenset(self.gapcats)
        self.markable = {kind: set(d) for kind, d in self.mark_kind.items()}
        # which categories take D on a side: the chart's lookup for a
        # complete constituent looking for a chain to join
        self.takers: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for (C, side), byD in self.emit.items():
            for D in byD:
                self.takers[(side, D)].append(C)
        self.w = feature_weights(self)     # log-linear weights (§ Chart)

    def coordinable(self, cats) -> bool:
        """CGEL's condition applied when a coordination is formed: its
        members must all be able to fill one and the same function slot
        (a nested coordination counts as fillable wherever a coordination
        is).  Checked here as well as at attachment so that coordinations
        no slot could take are never built."""
        need = {X for X in cats if not X.startswith("Coordination")}
        if len(need) <= 1:
            return True
        key = frozenset(need)
        cache = self.__dict__.setdefault("_coordinable", {})
        if key not in cache:
            cache[key] = any(need <= lic for lic in self.slots.values()) or \
                need <= ROOT_CATS
        return cache[key]

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
# the chart: an active chart over structured labels
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


class Cat(NamedTuple):
    """A category as a record.  The tables (built by the extractor from the
    treebank's strings) are keyed by ``key``, stored once at construction;
    the chart itself never parses a string, it compares fields.  Build one
    with ``cat(...)`` or ``Cat.parse(...)``."""
    key: str             # the table key: NP, V_aux:fin, GAP/NP, Clause[that]
    base: str            # NP, Clause, V_aux, GAP, NP+PP (a fused category), ...
    form: str = ""       # finiteness class of a verb or auxiliary: fin, nonfin, mod
    gap: str = ""        # base == GAP: the category the gap stands for
    marker: str = ""     # markers=feature: the word of the marker carried

    @classmethod
    @lru_cache(maxsize=None)
    def parse(cls, s: str) -> "Cat":
        marker = ""
        if s.endswith("]"):
            s, marker = s[:-1].split("[", 1)
        gap = ""
        if s.startswith(GAP + "/"):
            s, gap = GAP, s[len(GAP) + 1:]
        base, form = (s.split(":", 1) + [""])[:2]
        return cat(base, form, gap, marker)


@lru_cache(maxsize=None)
def cat(base: str, form: str = "", gap: str = "", marker: str = "") -> Cat:
    s = base
    if form:
        s += ":" + form
    if gap:
        s += "/" + gap
    if marker:
        s += "[" + marker + "]"
    return Cat(s, base, form, gap, marker)


COORDINATION = cat("Coordination")


class Label(NamedTuple):
    """What an edge is.  A field earns its place by a rule that reads it."""
    cat: Cat
    gaps: Tuple[str, ...] = ()              # categories still missing below
    binders: Tuple[str, ...] = ()           # binders waiting for a gap on the
                                            #   other side of the head (chains)
    used: FrozenSet[str] = frozenset()      # once-only functions attached (chains)
    members: FrozenSet[Cat] = frozenset()   # a coordination: its conjuncts'
                                            #   categories, nested ones flattened

    @property
    def dkey(self) -> str:
        """The table key of this constituent as a dependent."""
        return "Coordination" if self.members else self.cat.key

    @property
    def conjuncts(self) -> FrozenSet[Cat]:
        """What this constituent contributes to a coordination's members."""
        return self.members or frozenset({self.cat})


# what an edge still needs
LEFT, RIGHT, COMPLETE, CONJ, TAIL = "L", "R", "complete", "conj", "tail"
# agenda order within a span size, from the same-span derivations: a right
# chain before the constituent the head's empty left base completes with it,
# a constituent before the left chain the empty left base starts from it, a
# constituent before the conjunct it becomes, a conjunct before the tail it
# ends.  Every other derivation has strictly smaller tails.
RANK = {RIGHT: 0, COMPLETE: 1, LEFT: 2, CONJ: 3, TAIL: 4}
TIE = 1e-9          # two scores this close are a tie (see Chart.prefer)


class Edge(NamedTuple):
    id: int
    label: Label
    start: int
    end: int
    needed: str


class Chart:
    """An active chart.  An edge is ``(id, label, start, end, needed)``,
    one per distinct tuple; its score and its best derivation (``mode="max"``,
    Viterbi) or its inside mass (``mode="sum"``) are tables keyed by id, and
    with ``record=True`` every derivation is kept, in creation order, for the
    outside pass.

    ``needed`` says what the edge still wants: ``L`` a chain of left
    dependents of a head at ``end`` (span ``[start, end)`` excludes the head),
    ``R`` a chain of right dependents of a head at ``start`` (the span
    includes it), ``complete`` nothing, ``conj`` a coordinator-marked conjunct
    waiting for its tail, ``tail`` one or more conjuncts, the last marked,
    waiting for a first conjunct on the left.

    Edges are indexed by the position they grow at: ``at_start[j]`` and
    ``at_end[j]`` map a part of the label that a rule selects on (the
    category a chain wants, the gap state a coordination must share) to the
    set of edge ids there, so that each rule is an array lookup followed by
    a set scan over its real candidates.  The agenda is a heap by span size
    (then by ``RANK``), so every derivation of an edge is in place before the
    edge is popped and combined, and creation order is topological.  The
    support (which edges exist) is the same in both modes.
    """

    def __init__(self, g: "Grammar", ts: Sequence[str],
                 words: Optional[Sequence[str]] = None, maxgap: int = MAXGAP,
                 coord: bool = True, slash: bool = True, mode: str = "max",
                 record: bool = False, once: bool = True, finite: bool = True,
                 license: bool = True):
        self.g, self.ts = g, list(ts)
        self.once, self.finite, self.license = once, finite, license
        self.n = len(self.ts)
        self.words = list(words) if words else [None] * self.n
        self.maxgap, self.coord, self.slash = maxgap, coord, slash
        self.mode, self.record = mode, record
        self.w = g.w
        self.edges: List[Edge] = []
        self.score: List[float] = []
        self.back: List[tuple] = []                 # best derivation, by id
        self.derivs: List[Tuple[int, Tuple[int, ...], Tuple[tuple, ...]]] = []
        self._ids: Dict[tuple, int] = {}
        self.at_start: List[Dict[tuple, set]] = [defaultdict(set) for _ in range(self.n + 1)]
        self.at_end: List[Dict[tuple, set]] = [defaultdict(set) for _ in range(self.n + 1)]
        self.agenda: list = []
        self.roots: List[int] = []

    # -- the semiring ------------------------------------------------------
    def add(self, label: Label, start: int, end: int, needed: str,
            tails: Tuple[int, ...], feats: Tuple[tuple, ...], how: tuple) -> None:
        """One derivation of an edge: its score is the sum of its tails'
        scores and its features' weights.  New edges join the agenda."""
        val = 0.0
        for t in tails:
            val += self.score[t]
        for f in feats:
            val += self.w[f]
        key = (label, start, end, needed)
        eid = self._ids.get(key)
        if eid is None:
            eid = len(self.edges)
            self._ids[key] = eid
            self.edges.append(Edge(eid, label, start, end, needed))
            self.score.append(val)
            self.back.append(how)
            heapq.heappush(self.agenda, (end - start, RANK[needed], eid))
        elif self.mode == "max":
            cur = self.score[eid]
            if val > cur + TIE or (val >= cur - TIE and self.prefer(how, self.back[eid])):
                self.score[eid], self.back[eid] = val, how
        else:
            self.score[eid] = _logaddexp(self.score[eid], val)
        if self.record:
            self.derivs.append((eid, tails, feats))

    def prefer(self, new: tuple, old: tuple) -> bool:
        """The tie-break between two derivations of equal score: attach a
        dependent as low as possible (late closure), that is, prefer the
        derivation whose dependent is the larger, so that the material
        goes inside the nearer constituent rather than onto the higher
        head.  The features cannot tell the two apart (the ``dep`` feature
        names the head's category, not its class), and 86 of the 218
        sentences have such a tie; otherwise the first derivation found
        stands."""
        if new[0] == "attach" and old[0] == "attach":
            edges = self.edges
            dn, do = edges[new[3]], edges[old[3]]
            return dn.end - dn.start > do.end - do.start
        return False

    def mark_feature(self, kind: str, word: Optional[str], X: str):
        f = ("mark", kind, word, X)
        if f in self.w:
            return f
        f = ("markk", kind, X)
        return f if f in self.w else None

    # -- the loop ----------------------------------------------------------
    def run(self) -> "Chart":
        self._bases()
        edges, agenda = self.edges, self.agenda
        while agenda:
            _, _, eid = heapq.heappop(agenda)
            e = edges[eid]
            self._index(e)
            self._combine(e)
        n = self.n
        for e in edges:
            if e.start != 0 or e.end != n or e.label.gaps:
                continue
            lab = e.label
            if e.needed == COMPLETE:
                ok = all(m.base in ROOT_CATS for m in lab.members) if lab.members \
                    else lab.cat.base in ROOT_CATS
            elif e.needed == CONJ and self.g.markers != "dependent":
                ok = lab.cat.base in ROOT_CATS      # clause-initial "and"
            else:
                ok = False
            if ok:
                self.roots.append(e.id)
        return self

    def _bases(self) -> None:
        g, ts, W, slash = self.g, self.ts, self.w, self.slash
        for h in range(self.n):
            tok = ts[h]
            if tok == GAP:
                heads = [cat(GAP, gap=X) for X in g.gapcats]
            else:
                heads = [Cat.parse(tok)]
            for L in heads:
                if L.base in MARKERS:
                    continue                          # markers are never heads
                for C in g.proj.get(L.key, {}):
                    if C == "<leaf>":
                        continue
                    if ("stop", C, "L") not in W or ("stop", C, "R") not in W:
                        continue
                    g0 = (L.gap,) if (L.gap and slash) else NOGAPS
                    self.add(Label(cat(C), g0), h, h, LEFT, (),
                             (("proj", L.key, C), ("stop", C, "L")), ("base", L))
                    self.add(Label(cat(C)), h, h + 1, RIGHT, (),
                             (("stop", C, "R"),), ("base", None))
            # a bare leaf: a gap standing for X, or a name piece
            if tok == GAP:
                for X in g.gapcats:
                    L = cat(GAP, gap=X)
                    if ("leaf", L.key) in W:
                        self.add(Label(L, (X,) if slash else NOGAPS), h, h + 1,
                                 COMPLETE, (), (("leaf", L.key),), ("leaf", X))
            elif ("leaf", tok) in W:
                self.add(Label(Cat.parse(tok)), h, h + 1, COMPLETE, (),
                         (("leaf", tok),), ("leaf", None))

    def _index(self, e: Edge) -> None:
        lab, start, end = e.label, e.start, e.end
        if e.needed == COMPLETE:
            self.at_start[start][(COMPLETE, lab.dkey)].add(e.id)
            self.at_end[end][(COMPLETE, lab.dkey)].add(e.id)
            self.at_end[end][("conjunct", lab.gaps)].add(e.id)
        elif e.needed == RIGHT or e.needed == LEFT:
            self.at_start[start][(e.needed, lab.cat.key)].add(e.id)
            self.at_end[end][(e.needed, lab.cat.key)].add(e.id)
        elif e.needed == CONJ:
            self.at_end[end][(CONJ, lab.gaps)].add(e.id)
        else:
            self.at_start[start][(TAIL, lab.gaps)].add(e.id)

    def _combine(self, e: Edge) -> None:
        g, ts, edges = self.g, self.ts, self.edges
        lab, i, k = e.label, e.start, e.end
        if e.needed == COMPLETE:
            D = lab.dkey
            for C in g.takers.get(("R", D), ()):
                for rid in self.at_end[i].get((RIGHT, C), ()):
                    self.attach("R", edges[rid], e)
            for C in g.takers.get(("L", D), ()):
                for lid in self.at_start[k].get((LEFT, C), ()):
                    self.attach("L", edges[lid], e)
            if i >= 1 and ts[i - 1] == "Sdr" and g.markers != "dependent":
                self.mark(e)
            if g.markers == "dependent":              # marker already inside
                if ts[i] == "Coordinator" and k - i >= 2:
                    self.add(lab, i, k, CONJ, (e.id,), (("conj", "marked"),),
                             ("conj-arg", e.id))
            elif i >= 1 and ts[i - 1] == "Coordinator":
                mf = self.mark_feature("Coordinator", self.words[i - 1], D)
                if mf:
                    self.add(lab, i - 1, k, CONJ, (e.id,), (mf, ("conj", "marked")),
                             ("conj", e.id))
            if self.coord:
                for tid in self.at_start[k].get((TAIL, lab.gaps), ()):
                    self.coordinate(e, edges[tid])      # the first conjunct
                    self.more(e, edges[tid])            # a bare middle one
        elif e.needed == RIGHT:
            C = lab.cat.key
            for D in g.emit.get((C, "R"), ()):
                for did in self.at_start[k].get((COMPLETE, D), ()):
                    self.attach("R", e, edges[did])
            for lid in self.at_end[i].get((LEFT, C), ()):
                self.join(edges[lid], e)
        elif e.needed == LEFT:
            C = lab.cat.key
            for D in g.emit.get((C, "L"), ()):
                for did in self.at_end[i].get((COMPLETE, D), ()):
                    self.attach("L", e, edges[did])
            for rid in self.at_start[k].get((RIGHT, C), ()):
                self.join(e, edges[rid])
        elif e.needed == CONJ:
            if not self.coord:                        # COORD off: a conjunct
                return                                #   can still be a root
            self.add(Label(COORDINATION, lab.gaps, members=lab.conjuncts), i, k,
                     TAIL, (e.id,), (("coord", "last"),), ("last", e.id))
            for tid in self.at_start[k].get((TAIL, lab.gaps), ()):
                self.more(e, edges[tid])
        else:                                         # a tail: grows leftward
            for cid in self.at_end[i].get((CONJ, lab.gaps), ()):
                self.more(edges[cid], e)
            for aid in self.at_end[i].get(("conjunct", lab.gaps), ()):
                self.coordinate(edges[aid], e)
                self.more(edges[aid], e)

    # -- the rules ---------------------------------------------------------
    def attach(self, side: str, chain: Edge, dep: Edge) -> None:
        """Extend a chain by one complete dependent of its head."""
        g = self.g
        C, D = chain.label, dep.label
        h = chain.end if side == "L" else chain.start
        Ckey, Dkey = C.cat.key, D.dkey
        fs = g.emit.get((Ckey, side), {}).get(Dkey)
        if not fs:
            return
        head_class = self.ts[h]
        if D.members:                                 # CGEL: alike in function
            licensed = g.dep.get((Ckey, side), {})
            fs = [(f, p) for f, p in fs
                  if all((f, m.key) in licensed for m in D.members)]
            if not fs:
                return
        once, finite, license, slash = self.once, self.finite, self.license, self.slash
        maxgap, gapset, lic = self.maxgap, g.gapset, g.licensed
        used0, g0, b0 = C.used, C.gaps, C.binders
        gd = D.gaps
        nominal = C.cat.base in NOMINAL and D.cat.base in CLAUSAL and "Nom" in gd
        start, end = (dep.start, h) if side == "L" else (h, dep.end)
        tails, needed, ids = (chain.id, dep.id), chain.needed, (chain.id, dep.id)
        for f, _p in fs:
            if once and f in ONCE and f in used0:
                continue                              # at most once per head
            if finite and f == "Subj" and head_class not in FINITE:
                continue                              # a finite head licenses it
            if license and f in COMPLEMENT and (head_class, f) not in lic:
                continue                              # the head class licenses it
            gaps, binders = g0 + gd, b0
            if f in BINDERS:
                if gd:                                # a binder is gap-free
                    continue
                X = D.cat.base
                if X in gaps:
                    gaps = _remove(gaps, X)           # fills a gap below
                elif X in gapset:
                    binders = _add(binders, X)        # gap on the other side
                else:
                    continue                          # no gap can be an X
            elif nominal:
                gaps = _remove(gaps, "Nom")           # the head noun is the material
            if gd:
                gaps = tuple(sorted(gaps))
            if not slash:
                gaps, binders = NOGAPS, NOGAPS
            if len(gaps) > maxgap or len(binders) > maxgap:
                continue
            used = used0 | {f} if (once and f in ONCE) else used0
            self.add(Label(C.cat, gaps, binders, used), start, end, needed,
                     tails, (("dep", Ckey, side, f, Dkey),), ("attach", f) + ids)

    def join(self, left: Edge, right: Edge) -> None:
        """A left chain meets the right chain of the same head: a constituent.
        Pending binders cancel against open gaps across the head."""
        L, R = left.label, right.label
        gaps, binders = _cancel(L.gaps + R.gaps, L.binders + R.binders)
        if binders or len(gaps) > self.maxgap:
            return
        if L.used & R.used:
            return                                    # once-only on both sides
        self.add(Label(L.cat, gaps), left.start, right.end, COMPLETE,
                 (left.id, right.id), (), ("join", left.id, right.id))

    def mark(self, body: Edge) -> None:
        """A subordinator marks the constituent to its right."""
        lab, i = body.label, body.start
        word = self.words[i - 1]
        mf = self.mark_feature("Sdr", word, lab.dkey)
        if not mf:
            return
        X = cat(lab.cat.base, lab.cat.form, lab.cat.gap, word) \
            if self.g.markers == "feature" else lab.cat
        self.add(Label(X, lab.gaps, members=lab.members), i - 1, body.end, COMPLETE,
                 (body.id,), (mf,), ("mark", body.id, lab.cat.key))

    def more(self, conj: Edge, tail: Edge) -> None:
        """A conjunct followed by a tail: a longer tail.  A bare (unmarked)
        middle conjunct is a complete constituent that is not itself a
        coordination (which would duplicate the nested analysis)."""
        if conj.needed == COMPLETE and conj.label.members:
            return
        members = conj.label.conjuncts | tail.label.members
        if not self.g.coordinable({m.key for m in members}):
            return                                    # no slot takes them all
        feats = (("coord", "more"),) if conj.needed == CONJ \
            else (("conj", "bare"), ("coord", "more"))
        self.add(Label(COORDINATION, tail.label.gaps, members=members),
                 conj.start, tail.end, TAIL, (conj.id, tail.id), feats,
                 ("more", conj.id, tail.id))

    def coordinate(self, first: Edge, tail: Edge) -> None:
        """A first conjunct and a tail with the same gaps (across the board):
        a coordination, carrying its members' categories."""
        members = first.label.conjuncts | tail.label.members
        if not self.g.coordinable({m.key for m in members}):
            return
        self.add(Label(COORDINATION, tail.label.gaps, members=members),
                 first.start, tail.end, COMPLETE, (first.id, tail.id), (),
                 ("coord", first.id, tail.id))

    def log_inside(self) -> float:
        """log Z(string): the total mass of all analyses (mode "sum")."""
        vals = [self.score[r] for r in self.roots]
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
          once: bool = True, finite: bool = True, license: bool = True
          ) -> Optional[Parse]:
    """Viterbi parse of a lexical-category sequence (``GAP`` tokens included).

    ``coord=False`` switches the COORD schema off, ``slash=False`` the gap
    feature (gaps are then tokens with no binding discipline), ``once=False``
    the at-most-once rule for the functions the treebank never repeats on a
    head, and ``finite=False`` the licensing of a subject by a finite head;
    all exist for ablation.  See ``Chart`` for the edges and labels.
    """
    if len(ts) == 0:
        return None
    ch = Chart(g, ts, words, maxgap, coord, slash, mode="max",
               once=once, finite=finite, license=license).run()
    if not ch.roots:
        return None
    best = max(ch.roots, key=lambda r: ch.score[r])
    tree = _Rebuilder(ch).build(best)
    tree.edge = None
    link_gaps(tree)
    return Parse(tree, ch.score[best], tree.cat)


class _Rebuilder:
    """The tree of an edge from the best derivations (``Chart.back``)."""

    def __init__(self, ch: Chart):
        self.ch, self.g, self.ts, self.words = ch, ch.g, ch.ts, ch.words

    def leaf(self, i: int, X: Optional[str] = None) -> Node:
        if self.ts[i] == GAP:
            return Node(cat=GAP, feats={"for": [X or "?"]})
        return Node(cat=self.ts[i], feats={"t": [self.words[i] or self.ts[i]]})

    def build(self, eid: int) -> Node:
        e, how = self.ch.edges[eid], self.ch.back[eid]
        rule = how[0]
        if rule == "leaf":
            return self.leaf(e.start, how[1])
        if rule == "mark":
            body = self.build(how[1])
            marker = self.leaf(e.start)
            marker.edge = "Marker"
            return self.expand_marked(how[2], marker, body)
        if rule == "coord":
            first = self.build(how[1])
            first.edge = "Coordinate"
            return Node(cat="Coordination",
                        children=[first] + self.build_tail(how[2]))
        if rule == "conj-arg":
            return self.build(how[1])
        if rule == "conj":
            body = self.build(how[1])
            marker = self.leaf(e.start)
            marker.edge = "Marker"
            body.edge = "Head"
            return Node(cat=e.label.cat.key, children=[marker, body])
        assert rule == "join", how
        deps_l, L = self.chain("L", how[1])
        deps_r, _ = self.chain("R", how[2])
        return self.expand(e.label.cat.key, self.ch.edges[how[1]].end, L,
                           deps_l, deps_r)

    def build_tail(self, eid: int) -> List[Node]:
        how = self.ch.back[eid]
        if how[0] == "last":
            c = self.build(how[1])
            c.edge = "Coordinate"
            return [c]
        c = self.build(how[1])
        c.edge = "Coordinate"
        return [c] + self.build_tail(how[2])

    def chain(self, side: str, eid: int):
        """The dependents (function, node) of one side in surface order, and
        the head's base label."""
        out = []
        how = self.ch.back[eid]
        while how[0] == "attach":
            _, f, inner, dep = how
            node = self.build(dep)
            node.edge = f
            out.append((f, node))
            how = self.ch.back[inner]
        assert how[0] == "base", how
        return (out if side == "L" else list(reversed(out))), how[1]

    # -- unary re-expansion ---------------------------------------------------
    def expand(self, C: str, h: int, L: Cat, deps_l, deps_r) -> Node:
        chain = list(self.g.chain.get((C, L.key), (C, L.key)))
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
        head = self.leaf(h, L.gap or None)
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


def evaluate(sentences, g: Grammar, maxgap: int = MAXGAP, maxtok: int = MAXTOK,
             **sw) -> list:
    """One row per sentence; a sentence over ``maxtok`` tokens is not parsed
    and its row says ``excluded``."""
    rows = []
    for s in sentences:
        if len(sentence_tokens(s)) > maxtok:
            rows.append({"id": s.sent_id, "kind": _kind(s), "parsed": False,
                         "excluded": True})
            continue
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
    excluded = sum(1 for r in rows if r.get("excluded"))
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
    out = [f"{label}: parsed={len(ok)}/{len(rows) - excluded}"
           + (f" ({excluded} excluded over {MAXTOK} tokens)" if excluded else "") + "  "
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
                          ("LICENSE off", dict(license=False)),
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
