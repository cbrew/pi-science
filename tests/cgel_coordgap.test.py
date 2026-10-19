#!/usr/bin/env python3
"""Tests for the coordination / marker / gap parser (cgel_coordgap.py).
Run:  python3 tests/cgel_coordgap.test.py
"""
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import parse_cgel_file
from cgel_coordgap import (BINDERS, GAP, MARKERS, _chain_top, build_grammar,
                           fill_gaps, gap_bindings, head_chain, is_gap_label,
                           iter_events, parse, sentence_tokens, sentence_words)

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]


def find(sub):
    return next(s for s in SENTENCES if sub in s.sent)


class TestExtraction(unittest.TestCase):
    def test_markers_are_never_dependents_or_heads(self):
        g = build_grammar(SENTENCES)
        for (C, side), table in g.dep.items():
            for (f, D) in table:
                self.assertNotIn(D, MARKERS, (C, side, f, D))
        for L in g.proj:
            self.assertNotIn(L, MARKERS)

    def test_event_counts_match_corpus(self):
        kinds = Counter()
        gaps = 0
        for s in SENTENCES:
            for ev in iter_events(s):
                kinds[ev[0]] += 1
                if ev[0] == "proj":
                    gaps += is_gap_label(ev[2])     # inverted-auxiliary slot
                    gaps += sum(is_gap_label(D) for _, D in ev[3] + ev[4])
        # 131 Coordination nodes, one of them (etc.) has no conjunct list
        self.assertEqual(kinds["coord"], 130)
        # every Sdr/Coordinator token in a Marker slot (one Marker is a DP)
        n_markers = sum(1 for s in SENTENCES for n in s.root.iter_nodes()
                        if n.edge == "Marker" and n.cat in MARKERS)
        self.assertEqual(kinds["mark"], n_markers)
        # every gap is a dependent or the head slot of a folded node, except
        # those hanging off a node that cannot be folded (Coordination-headed)
        lost = 0
        for s in SENTENCES:
            parent = {c: n for n in s.root.iter_nodes() for c in n.children}
            for n in s.root.iter_nodes():
                if n.is_gap:
                    top = _chain_top(parent[n], parent)
                    chain = head_chain(top)
                    if not chain or chain[-1].cat in MARKERS:
                        lost += 1
        self.assertEqual(gaps + lost, 119)
        self.assertLessEqual(lost, 2)

    def test_tables_normalised(self):
        g = build_grammar(SENTENCES)
        for C, side, total in g.check_normalization():
            self.assertAlmostEqual(total, 1.0, places=9, msg=(C, side))
        for L, d in g.proj.items():
            self.assertAlmostEqual(sum(d.values()), 1.0, places=9, msg=L)


SHORT = [s for s in SENTENCES if len(sentence_tokens(s)) <= 12]


class TestParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = build_grammar(SENTENCES)
        cls.parsed = {s.sent_id: parse(cls.g, sentence_tokens(s), sentence_words(s))
                      for s in SHORT}

    def _parse(self, s, **kw):
        if not kw and s.sent_id in self.parsed:
            return self.parsed[s.sent_id]
        return parse(self.g, sentence_tokens(s), sentence_words(s), **kw)

    def test_coverage_and_token_preservation(self):
        parsed = 0
        for s in SHORT:
            pr = self._parse(s)
            if pr is None:
                continue
            parsed += 1
            toks = sentence_tokens(s)
            leaves = [n for n in pr.tree.iter_nodes()
                      if (n.is_lexical and not n.children) or n.is_gap]
            self.assertEqual(len(leaves), len(toks), s.sent_id)
            self.assertEqual(sum(1 for n in leaves if n.is_gap),
                             toks.count(GAP), s.sent_id)
        self.assertGreaterEqual(parsed, len(SHORT) - 2)

    def test_coordination_shape(self):
        pr = self._parse(find("fire alarm and strobe light"))
        coords = [n for n in pr.tree.iter_nodes() if n.cat == "Coordination"]
        self.assertTrue(coords)
        for co in coords:
            conj = [c for c in co.children if c.edge == "Coordinate"]
            self.assertEqual(len(conj), len(co.children))
            self.assertGreaterEqual(len(conj), 2)
            self.assertEqual(len({c.cat for c in conj}), 1, "like conjuncts")
            last = conj[-1]
            self.assertEqual(last.children[0].edge, "Marker")
            self.assertEqual(last.children[0].cat, "Coordinator")

    def test_subordinator_marks_a_clause(self):
        pr = self._parse(find("what a remarkable claim to make"))
        sdr = next(n for n in pr.tree.iter_nodes() if n.cat == "Sdr")
        self.assertEqual(sdr.edge, "Marker")
        parent = next(n for n in pr.tree.iter_nodes() if sdr in n.children)
        self.assertEqual(parent.children[0], sdr)
        self.assertIn(parent.cat, {"VP", "Clause", "Clause_rel"})

    def test_gaps_need_binders(self):
        # a lone gap has nothing to bind it: no parse under SLASH, a parse
        # (a gap-headed clause) with the discipline off
        self.assertIsNone(parse(self.g, [GAP]))
        self.assertIsNotNone(parse(self.g, [GAP], slash=False))
        # "Adj GAP": no binder of any category the gap could stand for
        self.assertIsNone(parse(self.g, ["Adj", GAP]))
        # "V_aux GAP": the auxiliary is forced into the Prenucleus slot and
        # the gap stands for it (the head slot of the inverted clause)
        pr = parse(self.g, ["V_aux", GAP])
        self.assertIsNotNone(pr)
        self.assertIn("Prenucleus", {n.edge for n in pr.tree.iter_nodes()})
        gap = next(n for n in pr.tree.iter_nodes() if n.cat == GAP)
        self.assertEqual(gap.get("for"), "V_aux")
        binder = next(n for n in pr.tree.iter_nodes()
                      if n.index == gap.index and n.cat != GAP)
        self.assertEqual(binder.cat, "V_aux")
        # "GAP V" does parse: a gap-headed clause may bind its own head gap
        # through a Postnucleus (one can never tell when -- ... Alan was ...)
        pr = parse(self.g, [GAP, "V"])
        self.assertIsNotNone(pr)
        self.assertIn("Postnucleus", {n.edge for n in pr.tree.iter_nodes()})

    def test_marker_modes_run(self):
        s = find("what a remarkable claim to make")
        for mode in ("schema", "feature", "dependent"):
            g = build_grammar(SENTENCES, markers=mode)
            for C, side, total in g.check_normalization():
                self.assertAlmostEqual(total, 1.0, places=9, msg=(mode, C, side))
            pr = parse(g, sentence_tokens(s), sentence_words(s))
            self.assertIsNotNone(pr, mode)
            sdr = next(n for n in pr.tree.iter_nodes() if n.cat == "Sdr")
            self.assertEqual(sdr.edge, "Marker", mode)

    def test_every_gap_is_bound_to_material_of_its_category(self):
        # every gap in every parse is co-indexed with exactly one binder
        # whose category is the category the gap stands for
        for s in SHORT:
            pr = self._parse(s)
            if pr is None:
                continue
            binders = {n.index: n for n in pr.tree.iter_nodes()
                       if n.index and n.cat != GAP}
            for n in pr.tree.iter_nodes():
                if n.cat == GAP:
                    self.assertIsNotNone(n.index, s.sent_id)
                    b = binders[n.index]
                    want = n.get("for")
                    # a binder in the Head slot of a nominal supplies a Nom
                    got = "Nom" if b.edge == "Head" else b.cat
                    self.assertEqual(got.split("[")[0], want, (s.sent_id, b.cat))
            self.assertEqual(len(binders), len(set(binders)))

    def test_fill_copies_the_fronted_auxiliary(self):
        # would this -- be fine: the gap is the head slot of the VP and the
        # material is the fronted auxiliary; filling restores "this would be"
        s = find("would this -- be fine")
        pr = self._parse(s)
        self.assertEqual(gap_bindings(pr.tree), gap_bindings(s.root))
        filled = fill_gaps(pr.tree)
        self.assertFalse(any(n.cat == GAP for n in filled.iter_nodes()))
        words = [n.surface for n in filled.iter_nodes() if n.is_lexical]
        self.assertEqual(words.count("would"), 2)
        vp_heads = [c for n in filled.iter_nodes() if n.cat == "VP"
                    for c in n.children if c.edge == "Head" and c.surface == "would"]
        self.assertTrue(vp_heads)

    def test_across_the_board_sharing(self):
        # two conjuncts each with an object gap, one postposed binder
        # (the 36-token four-way case is the slowest sentence in the corpus
        # and is deliberately not parsed here)
        s = find("receive -- and be prohibited from giving away -- a horse")
        pr = self._parse(s)
        self.assertIsNotNone(pr)
        gaps = [n for n in pr.tree.iter_nodes() if n.cat == GAP]
        self.assertEqual(len(gaps), 2)
        # every coordination whose conjuncts all contain a gap of the same
        # category shares one index across them (across the board)
        atb = 0
        for co in (n for n in pr.tree.iter_nodes() if n.cat == "Coordination"):
            per = [[x for x in c.iter_nodes() if x.cat == GAP]
                   for c in co.children if c.edge == "Coordinate"]
            if all(per) and len({x.get("for") for g in per for x in g}) == 1:
                atb += 1
                self.assertEqual(len({x.index for g in per for x in g}), 1)
        self.assertGreaterEqual(atb, 1, "the shared gaps sit inside a coordination")
        filled = fill_gaps(pr.tree)
        self.assertFalse(any(n.cat == GAP for n in filled.iter_nodes()))

    def test_coordination_switch(self):
        s = find("fire alarm and strobe light")
        self.assertIsNotNone(self._parse(s))
        self.assertIsNone(self._parse(s, coord=False))


if __name__ == "__main__":
    unittest.main(verbosity=1)
