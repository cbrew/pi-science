#!/usr/bin/env python3
"""Empirical conformance checker for the two "grammar of the treebank"
conventions described in docs/cgel-conventions.md:

  1. the XBAR (projection) convention -- which categories may dominate which;
  2. the HEAD RULE -- which category each :Head child belongs to, given the
     parent category (function labels and constituent labels are not
     independent).

The rule tables live in ``cgel_grammar.py`` (induced from the corpus itself,
all 220 trees).  This checker runs the *strict* X-bar skeleton: the handful of
exceptions are intentional, note-flagged annotator choices and are listed by
the script.

Run:  python3 cgel_conventions.py [cgel/*.cgel]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Counter as CounterT, Tuple

from cgel_grammar import EDGE_PARENTS, EDGE_CHILDREN, HEAD_ALLOWED, ROOT, XBAR_STRICT
from cgel_reader import parse_cgel_file

CGEL = Path(__file__).resolve().parent / "cgel"
FUSED = {"NP+PP", "NP+AdvP", "NP+AdjP", "NP+Clause"}


def check_file(path: str, verbose: bool = False) -> Tuple[int, int, "CounterT[str,int]"]:
    """Return (sentences, exceptions, exception-by-type counter)."""
    n_sent = 0
    n_exc = 0
    kinds: CounterT[str, int] = Counter()

    def exc(kind: str, sent: str, msg: str) -> None:
        nonlocal n_exc
        n_exc += 1
        kinds[kind] += 1
        if verbose:
            print(f"   {kind:16s} {sent}: {msg}")

    for s in parse_cgel_file(path):
        n_sent += 1
        for n in s.root.iter_nodes():
            if n.cat not in FUSED and n.cat in XBAR_STRICT:
                for c in n.children:
                    if c.cat not in XBAR_STRICT.get(n.cat, set()):
                        exc("xbar", s.sent_id, f"{n.cat} dominates {c.cat}")
            for c in n.children:
                if c.edge == "Head":
                    if c.cat not in HEAD_ALLOWED.get(n.cat, set()):
                        exc("head", s.sent_id, f"{n.cat}:Head -> {c.cat}")
                if c.edge in EDGE_PARENTS and n.cat not in EDGE_PARENTS[c.edge]:
                    exc("fun-parent", s.sent_id,
                        f":{c.edge} under {n.cat} (child {c.cat})")
                if c.edge == "Coordinate" and n.cat != "Coordination":
                    exc("coordinate", s.sent_id, f":Coordinate under {n.cat}")
                if c.edge == "Marker" and c.cat not in {"Sdr", "Coordinator", "DP"}:
                    exc("marker", s.sent_id, f":Marker -> {c.cat}")
                if c.cat not in EDGE_CHILDREN.get(c.edge, set()):
                    exc("fun-child", s.sent_id, f":{c.edge} -> {c.cat} under {n.cat}")
    return n_sent, n_exc, kinds


def main(argv=None) -> int:
    verbose = "--verbose" in (argv or sys.argv)
    files = ([a for a in argv if not a.startswith("--")] if argv
             else [str(p) for p in sorted(CGEL.glob("*.cgel"))]) or \
            [str(p) for p in sorted(CGEL.glob("*.cgel"))]
    tot_s, tot_e, kinds = 0, 0, Counter()
    for f in files:
        s, e, k = check_file(f, verbose=verbose)
        tot_s += s; tot_e += e; kinds.update(k)
        print(f"{f}: {s} sentences, {e} exceptions")
    print(f"\ntotal: {tot_s} sentences, {tot_e} exceptions")
    for k, n in kinds.most_common():
        print(f"   {k:14s} {n}")
    return 0  # exceptions are informative, not failures


if __name__ == "__main__":
    raise SystemExit(main())
