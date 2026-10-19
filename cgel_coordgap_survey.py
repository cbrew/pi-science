"""Corpus survey behind docs/cgel-coordination-gaps.md.

Prints the tables that the coordination / gap proposal relies on:
coordination shapes, where coordinators and subordinators sit, gap sites,
binder sites, the gap-to-binder path, and the across-the-board check.

Run:  python3 cgel_coordgap_survey.py
"""
from __future__ import annotations

import collections
from pathlib import Path

from cgel_reader import Node, parse_cgel_file

CGEL = Path(__file__).resolve().parent / "cgel"


def parent_map(root: Node) -> dict:
    pm = {}
    for n in root.iter_nodes():
        for c in n.children:
            pm[c] = n
    return pm


def ancestors(n: Node, pm: dict) -> list:
    out = []
    while n in pm:
        n = pm[n]
        out.append(n)
    return out


def show(title: str, counter: collections.Counter, limit: int = 40) -> None:
    print(f"\n{title}")
    for k, v in counter.most_common(limit):
        print(f"  {v:4d}  {k}")


def survey_coordination(sents) -> None:
    shapes, cats, marker_at, parent = (collections.Counter() for _ in range(4))
    for s in sents:
        pm = parent_map(s.root)
        for n in s.root.iter_nodes():
            if n.cat != "Coordination":
                continue
            shapes[tuple(c.edge for c in n.children)] += 1
            conj = [c for c in n.children if c.edge == "Coordinate"]
            cats["like" if len({c.cat for c in conj}) == 1 else
                 "unlike:" + "+".join(c.cat for c in conj)] += 1
            for i, c in enumerate(conj):
                for m in c.children:
                    if m.edge in ("Marker", "Marker-Head"):
                        marker_at[(f"conjunct {i}", m.cat,
                                   "first child" if c.children[0] is m
                                   else "NOT first")] += 1
            p = pm.get(n)
            parent[(p.cat if p else "ROOT", n.edge)] += 1
    print("=== coordination (131 nodes) ===")
    show("child-edge shapes", shapes)
    show("conjunct categories", cats)
    show("marker position (conjunct index, marker cat, position)", marker_at)
    show("parent category / edge of the Coordination node", parent)


def survey_markers(sents) -> None:
    sdr = collections.Counter()
    for s in sents:
        pm = parent_map(s.root)
        for n in s.root.iter_nodes():
            if n.cat == "Sdr":
                p = pm[n]
                sdr[(n.surface, p.cat, p.edge,
                     "first child" if p.children[0] is n else "NOT first")] += 1
    show("subordinators (word, parent cat, parent edge, position)", sdr)


def survey_gaps(sents) -> None:
    site, binder, path_edges, discharge = (collections.Counter() for _ in range(4))
    lca_child, before, crossed, atb, open_slashes = (
        collections.Counter() for _ in range(5))
    ngaps = 0
    for s in sents:
        pm = parent_map(s.root)
        binders = {n.index: n for n in s.root.iter_nodes()
                   if n.index and not n.is_gap}
        order = {n: i for i, n in enumerate(s.root.iter_nodes())}
        for g in (n for n in s.root.iter_nodes() if n.is_gap):
            ngaps += 1
            b = binders[g.index]
            site[(g.edge, pm[g].cat)] += 1
            binder[(b.edge, b.cat)] += 1
            before["binder precedes gap" if order[b] < order[g]
                   else f"gap precedes binder ({b.edge})"] += 1
            ga = ancestors(g, pm)
            bset = set(ancestors(b, pm))
            lca = next(a for a in ga if a in bset)
            lca_child["binder is a child of the lowest common ancestor"
                      if pm[b] is lca else f"binder deeper ({s.sent_id})"] += 1
            path = ga[:ga.index(lca)]
            for a in path:
                path_edges[a.edge] += 1
            coords = [a for a in path if a.cat == "Coordination"]
            crossed[len(coords)] += 1
            for co in coords:
                conj = [c for c in co.children if c.edge == "Coordinate"]
                has = sum(any(x.is_gap and x.index == g.index
                              for x in c.iter_nodes()) for c in conj)
                atb[(len(conj), has)] += 1
            discharge[(lca.cat, b.edge, b.cat)] += 1

        def walk(n: Node):
            gaps, bs = set(), set()
            if n.is_gap:
                gaps.add(n.index)
            elif n.index:
                bs.add(n.index)
            for c in n.children:
                g2, b2 = walk(c)
                gaps |= g2
                bs |= b2
            if not n.is_gap:
                open_slashes[len(gaps - bs)] += 1
            return gaps, bs
        walk(s.root)
    print(f"\n=== gaps ({ngaps}) ===")
    show("gap site (edge, parent cat)", site)
    show("binder (edge, cat)", binder)
    show("linear order", before)
    show("locality", lca_child)
    show("edges on the path from gap up to the discharging node", path_edges)
    show("Coordination nodes crossed on that path", crossed)
    show("across-the-board check (conjuncts, conjuncts containing the gap)", atb)
    show("discharging node (cat, binder edge, binder cat)", discharge)
    show("nodes by number of simultaneously open gaps", open_slashes)


def main() -> None:
    sents = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]
    survey_coordination(sents)
    survey_markers(sents)
    survey_gaps(sents)


if __name__ == "__main__":
    main()
