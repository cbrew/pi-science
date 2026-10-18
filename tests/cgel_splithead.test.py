#!/usr/bin/env python3
"""Tests for the Eisner split-head generative model (cgel_splithead.py).

Run:  python3 tests/cgel_splithead.test.py
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import parse_cgel_file
from cgel_splithead import (SplitHead, iter_events, _dominant_child, _head_leaf,
                            HEAD_EDGES)

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]


class TestExtraction(unittest.TestCase):
    def test_every_internal_node_is_one_event(self):
        for s in SENTENCES[::25]:
            internal = sum(1 for n in s.root.iter_nodes() if n.children)
            events = sum(1 for _ in iter_events(s))
            self.assertEqual(internal, events, s.sent_id)

    def test_no_multiple_heads(self):
        # at most one dominant (head-line) child per node
        for s in SENTENCES:
            for n in s.root.iter_nodes():
                heads = [c for c in n.children if c.edge in HEAD_EDGES]
                self.assertLessEqual(len(heads), 1, s.sent_id)

    def test_projection_has_lexical_head(self):
        for s in SENTENCES[::40]:
            for ev in iter_events(s):
                if ev[0] == "proj":
                    _, cat, pcat, _, _ = ev
                    self.assertTrue(pcat, ev)


class TestModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = SplitHead.fit(SENTENCES, alpha=1.0)

    def test_normalization(self):
        # every (cat, side): p_stop + sum p_dep must be exactly 1, so the
        # split-head has NO partition-function / depth-bound problem
        for cat, side, nev, s, sd, tot, mass, expect in \
                self.model.check_normalization():
            self.assertAlmostEqual(tot, 1.0, places=9, msg=f"{cat} {side}")
            self.assertAlmostEqual(mass, 1.0, places=6, msg=f"{cat} {side}")
            self.assertLess(expect, 20.0)   # finite expected dependents

    def test_anchor_normalized_per_pos(self):
        by = {}
        for (p, c), v in self.model.anchor.items():
            by.setdefault(p, 0.0)
            by[p] += v
        for p, s in by.items():
            self.assertAlmostEqual(s, 1.0, places=6, msg=p)

    def test_all_sentences_finite(self):
        for s in SENTENCES[::20]:
            self.assertTrue(math.isfinite(self.model.loglik(s)), s.sent_id)

    def test_directionality_is_sharp(self):
        # NP determiners attach on the left, verbs' complements on the right
        det_left = max((self.model.dep.get(("NP", "L", ("Det", "DP")), 0),
                        self.model.dep.get(("Nom", "L", ("Det", "DP")), 0)))
        obj_right = self.model.dep.get(("VP", "R", ("Obj", "NP")), 0)
        self.assertGreater(det_left, 0.0)
        self.assertGreater(obj_right, 0.0)
        # verbs overwhelmingly take arguments to the right
        self.assertGreater(obj_right,
                           self.model.dep.get(("VP", "L", ("Obj", "NP")), 0))


if __name__ == "__main__":
    unittest.main(verbosity=1)
