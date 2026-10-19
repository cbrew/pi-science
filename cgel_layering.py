"""Layering: from a head with ordered, function-labelled dependents to the
treebank's chain of projection layers.

The CGELBank manual (as quoted in Brew's *CGEL phenomena* notes) states its
layering as a policy, not a statistical regularity:

* "If a phrase of type XP contains multiple dependents, these will generally
  be layered so as to attach one at a time going outward from the head,
  forming intermediate XP constituents."
* "multiple (internal, non-extraposed) complements within a VP will
  typically attach on the same level."
* "In NP structure, complements and modifiers are treated the same: each
  attaches within a separate Nom layer."  The determiner is external
  (NP over Nom).
* "Unary branches are always shown" / "nodes are never omitted".
* "a modifier naturally comes between a head and its complement, so the
  inner VP will contain the modifier whereas the outer VP will add the
  complement."
* An auxiliary heads a VP whose complement is a clause; the subject
  attaches at Clause over VP; the displaced subject is a complement in
  the VP; the extraposed subject sits in an outer VP layer.

If that is so, the layering is a deterministic function of the head's
class, the category the context requires at the top, and the dependents
in linear order with their functions.  ``layer()`` is that function and
``check_against_gold()`` measures how often it reproduces the treebank's
own layering, listing the residue.  It is tested before it is used for
anything.

Run:  python3 cgel_layering.py
"""
from __future__ import annotations

import collections
from typing import Dict, List, Optional, Sequence, Tuple

from cgel_reader import Node

# base projection of each word class (the layer over the word)
BASE = {"N": "Nom", "N_pro": "Nom", "N_c": "Nom", "V": "VP", "V_aux": "VP",
        "GAP": "VP", "P": "PP", "Adj": "AdjP", "Adj_c": "AdjP", "Adv": "AdvP",
        "D": "DP", "Int": "IntP"}
# maximal projection reached by adding a subject / determiner layer
MAXIMAL = {"Nom": "NP", "VP": "Clause"}

COMPLEMENTS = frozenset({"Obj", "Obj_ind", "Obj_dir", "Comp", "Comp_ind",
                         "PredComp", "Particle", "DisplacedSubj",
                         "Obj+Mod", "Obj+PredComp/Comp"})
MODIFIERS = frozenset({"Mod", "Supplement", "Vocative", "Flat"})
DISPLACED = frozenset({"Prenucleus", "Postnucleus", "Head-Prenucleus"})
OUTER_VP = frozenset({"ExtraposedSubj"})          # an outer VP layer

Dep = Tuple[int, str]                              # (position, function)
Layer = Tuple[str, Tuple[str, ...]]                # (category, functions)


def layer(head_class: str, head_pos: int, deps: Sequence[Dep], top: str,
          marker_words: Optional[Dict[int, str]] = None) -> List[Layer]:
    """The chain of layers, inner to outer, each as (category, functions
    attached there, sorted).  ``top`` is the category the context requires
    (``NP`` or ``Nom``, ``Clause`` or ``Clause_rel``, ``PP`` or
    ``PP_strand``); ``marker_words`` maps a Marker's position to its word."""
    base = BASE.get(head_class.split(":")[0], head_class)   # V:fin -> V
    if base == "PP" and top == "PP_strand":
        base = "PP_strand"
    rel = top == "Clause_rel"
    clause = "Clause_rel" if rel else "Clause"
    marker_words = marker_words or {}
    by_dist = sorted(deps, key=lambda d: abs(d[0] - head_pos))

    comps = [d for d in by_dist if d[1] in COMPLEMENTS]
    mods = [d for d in by_dist if d[1] in MODIFIERS]
    markers = [d for d in deps if d[1] == "Marker"]
    subj = [d for d in deps if d[1] == "Subj"]
    det = [d for d in deps if d[1] == "Det"]
    displaced = [d for d in by_dist if d[1] in DISPLACED]
    outer_vp = [d for d in deps if d[1] in OUTER_VP]
    other = [d for d in deps if d[1] not in COMPLEMENTS | MODIFIERS | DISPLACED
             | OUTER_VP | {"Marker", "Subj", "Det"}]

    layers: List[Layer] = []

    def push(cat, fs):
        layers.append((cat, tuple(sorted(fs))))

    flats = [d for d in deps if d[1] == "Flat"]
    mods = [m for m in mods if m[1] != "Flat"]
    if flats:                                   # name pieces sit on the word node
        push(head_class, [d[1] for d in flats])

    nominal = base in ("Nom", "DP") and top in ("NP", "Nom")
    front: List[Dep] = []
    if nominal:
        # a nominal: a fused determiner-head (D) projects Nom layers too;
        # complements innermost, then modifiers nearest first, one per layer
        if base == "DP":
            push("DP", [])
        seq = comps + [m for m in mods if m[1] != "Supplement"] + other
        if not seq:
            push("Nom", [])
        for d in seq:
            push("Nom", [d[1]])
        base = "Nom"
        mods = [m for m in mods if m[1] == "Supplement"]
    else:
        # verbs, prepositions, adjectives, adverbs, determinatives:
        # complements share the layer over the word, unless a modifier lies
        # between the head and a complement, in which case that modifier
        # takes the inner layer and the complements the next
        supp = [m for m in mods if m[1] == "Supplement"] if base == "VP" else []
        # a modifier to the left of the subject cannot be inside the VP:
        # it is a clause-layer modifier (front position), one layer each
        if base == "VP" and subj:
            front = [m for m in mods if m[0] < subj[0][0] and m not in supp]
        mods = [m for m in mods if m not in supp and m not in front]
        inner_mods = []
        if comps:
            nearest_comp = min(abs(c[0] - head_pos) for c in comps)
            inner_mods = [m for m in mods if abs(m[0] - head_pos) < nearest_comp
                          and (m[0] - head_pos) * (comps[0][0] - head_pos) > 0]
        rest_mods = [m for m in mods if m not in inner_mods]
        if inner_mods:
            for m in inner_mods:
                push(base, [m[1]])
            push(base, [c[1] for c in comps] + [o[1] for o in other])
        elif comps or other:
            push(base, [c[1] for c in comps] + [o[1] for o in other])
        elif not rest_mods:
            push(base, [])
        for m in rest_mods:
            push(base, [m[1]])
        for d in outer_vp:
            push(base, [d[1]])
        mods = supp
    # markers: the infinitival "to" is its own VP layer below the clause; a
    # subordinator is its own clause layer above the subject layer; any
    # other marker (a coordinator) is the outermost layer of the top category
    sdr_to = [m for m in markers if marker_words.get(m[0]) == "to"]
    sdr_cl = [m for m in markers if marker_words.get(m[0]) in
              ("that", "if", "whether", "for") and m not in sdr_to]
    coord = [m for m in markers if m not in sdr_to and m not in sdr_cl]
    for m in sdr_to:
        push(base, ["Marker"])
    # maximal projection: determiner (and supplement) over Nom, subject (and
    # supplement) over VP
    cur = base
    if base == "Nom" and (det or mods or top == "NP" or displaced):
        cur = "NP"
        push(cur, [d[1] for d in det] + [m[1] for m in mods])
    if base == "VP" and (subj or mods or sdr_cl or top in ("Clause", "Clause_rel")
                         or displaced):
        cur = clause
        push(cur, [d[1] for d in subj] + [m[1] for m in mods])
    for m in (front if base == "VP" else []):
        push(cur, [m[1]])
    for m in sdr_cl:
        push(cur, ["Marker"])
    for d in displaced:
        push(cur, [d[1]])
    for m in coord:
        push(cur if cur != base or top == cur else top, ["Marker"])
    return layers


# ---------------------------------------------------------------------------
# gold comparison
# ---------------------------------------------------------------------------

def gold_heads(root: Node):
    """For every head in a gold tree: (class, head position, deps, top,
    marker words, gold layers inner->outer)."""
    import cgel_coordgap as P
    pos = P.leaf_positions(root)
    spans = P._spans(root, pos)
    parent = {c: n for n in root.iter_nodes() for c in n.children}
    for n in root.iter_nodes():
        if (n in parent and P._is_head_child(n)) or n.cat in ("GAP", "Coordination"):
            continue
        if n.is_lexical and not n.children:
            continue
        chain = P.head_chain(n)
        if not chain or chain[-1].cat in P.MARKERS:
            continue
        leaf = chain[-1]
        hp = pos[leaf]
        deps: List[Dep] = []
        words: Dict[int, str] = {}
        gold: List[Layer] = []
        for node in reversed(chain[:-1]):
            fs = []
            for c in node.children:
                if c in chain:
                    continue
                a, _ = spans[c]
                p = pos[c] if c in pos else a
                deps.append((p, c.edge))
                fs.append(c.edge)
                if c.edge == "Marker":
                    words[p] = (c.surface or "").lower()
            gold.append((node.cat, tuple(sorted(fs))))
        cls = "GAP" if leaf.is_gap else leaf.cat
        yield cls, hp, sorted(deps), n.cat, words, gold


def check_against_gold(sentences, show: int = 10) -> dict:
    exact = total = 0
    residue = collections.Counter()
    examples = {}
    for s in sentences:
        for cls, hp, deps, top, words, gold in gold_heads(s.root):
            total += 1
            got = layer(cls, hp, deps, top, words)
            if got == gold:
                exact += 1
                continue
            key = (cls, tuple(f for _, f in deps),
                   " > ".join(f"{c}{list(f)}" for c, f in gold),
                   " > ".join(f"{c}{list(f)}" for c, f in got))
            residue[key] += 1
            examples.setdefault(key, s.sent)
    print(f"heads: {total}; layering reproduced exactly: {exact} ({100 * exact // total}%)")
    print(f"\nresidue, largest kinds first (class, functions, gold, ours):")
    for key, k in residue.most_common(show):
        cls, fs, g, o = key
        print(f"  {k:4d}  {cls} {list(fs)}\n          gold: {g}\n          ours: {o}\n          e.g. {examples[key][:80]}")
    return {"total": total, "exact": exact, "residue": residue}


if __name__ == "__main__":
    import cgel_coordgap as P
    check_against_gold(P.load_corpus(), show=12)
