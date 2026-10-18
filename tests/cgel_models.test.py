#!/usr/bin/env python3
"""Smoke tests for cgel_models.py: exactness of the DP, support restriction,
normalisation, and the A-vs-B relationship.  Run:  python3 tests/cgel_models.test.py"""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_grammar import EDGES, ROOT, ROOT_CATS, allowed
from cgel_models import (
    ModelA,
    ModelB,
    attested_assignment,
    assignment_to_tree,
    fit_loglinear,
    is_conforming,
    iter_slots,
    make_skeleton,
    fit_structured,
)
from cgel_reader import Node as RNode
from cgel_reader import parse_cgel_file

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel")) for s in parse_cgel_file(str(f))]


def skeleton_of(substr):
    for s in SENTENCES:
        if substr in s.sent_id:
            return s, make_skeleton(s.root)
    raise AssertionError(f"no sentence {substr}")


class TestModelA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ModelA.fit(SENTENCES, alpha=1.0)

    def test_normalised(self):
        self.assertAlmostEqual(sum(self.model.p_cat.values()), 1.0, places=10)
        self.assertAlmostEqual(sum(self.model.p_edge.values()), 1.0, places=10)

    def test_independent_label_draws(self):
        # every node draws independently from the full label space: the model
        # must assign positive probability to a "garbage" labelling
        s, sk = skeleton_of("IsThatWhatYouCall")
        assign = attested_assignment(s)
        # corrupt one category to a nonsense one (e.g. a word cat under a phrase)
        n = next(slot for slot in iter_slots(sk) if slot.is_variable).node
        assign[n] = ("N", assign[n][1])
        self.assertGreater(self.model.prob(sk, assign), 0.0)

    def test_attested_nonzero(self):
        for s in SENTENCES[::40]:
            sk = make_skeleton(s.root)
            a = attested_assignment(s)
            self.assertGreater(self.model.prob(sk, a), 0.0)


class TestModelB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = ModelA.fit(SENTENCES, alpha=1.0)
        cls.b = ModelB(cls.a.p_cat, cls.a.p_edge)

    def test_attested_conforms(self):
        for s in SENTENCES:
            sk = make_skeleton(s.root)
            self.assertTrue(is_conforming(attested_assignment(s), sk),
                            f"attested analysis must conform: {s.sent_id}")

    def test_nonconforming_has_zero_prob(self):
        s, sk = skeleton_of("IsThatWhatYouCall")
        assign = attested_assignment(s)
        # the root's incoming edge may only be ROOT; relabel it "Obj"
        root_node = sk.node
        root_cat = assign[root_node][0]
        assign[root_node] = (root_cat, "Obj")
        self.assertFalse(is_conforming(assign, sk))
        self.assertEqual(self.b.prob(sk, assign), 0.0)

    def test_Z_exact_vs_bruteforce(self):
        # toy skeleton: root -> one variable child -> one fixed leaf N
        # (incoming edge Flat), so the child must be an N/D container.
        from cgel_models import Slot
        from cgel_reader import Node as RNode
        from cgel_grammar import ALL_CATS
        leaf = Slot(fixed_cat="N", node=RNode(cat="N", edge="Flat"))
        child = Slot(fixed_cat=None, children=[leaf])
        root = Slot(fixed_cat=None, children=[child])
        model = self.b
        z_brute = 0.0
        for rc in ROOT_CATS:
            for e in EDGES:
                for cc in ALL_CATS:
                    if allowed(rc, e, cc) and allowed(cc, "Flat", "N"):
                        z_brute += math.exp(model.weight_cat[rc]
                                            + model.weight_cat[cc]
                                            + model.weight_edge[e])
        _, z = model.up_messages(root)
        self.assertAlmostEqual(math.exp(z), z_brute, places=8)

    def test_marginals_normalised(self):
        s, sk = skeleton_of("Here-sThePaper")
        cat_marg, edge_marg = self.b.marginals(sk)
        for i, (slot, d) in enumerate(cat_marg.items()):
            if slot.is_variable:
                self.assertAlmostEqual(sum(math.exp(v) for v in d.values()),
                                      1.0, places=8, msg=f"cat slot {i}")
        for i, (slot, d) in enumerate(edge_marg.items()):
            if slot.is_variable and slot is not sk:  # root has no edge marginal
                self.assertAlmostEqual(sum(math.exp(v) for v in d.values()),
                                      1.0, places=8, msg=f"edge slot {i}")

    def test_samples_all_conform(self):
        s, sk = skeleton_of("Here-sThePaper")
        rng = random.Random(0)
        from cgel_grammar import ROOT_CATS
        for assign in self.b.sample(sk, 30, rng):
            self.assertTrue(is_conforming(assign, sk))
            tree = assignment_to_tree(sk, assign)
            self.assertIn(tree.cat, ROOT_CATS)

    def test_B_beats_A_on_attested(self):
        gains = []
        for s in SENTENCES[::7]:   # subsampled for speed
            sk = make_skeleton(s.root)
            a = attested_assignment(s)
            la = self.a.logp(sk, a)
            lb = self.b.logp(sk, a)
            self.assertGreaterEqual(lb, la - 1e-9, s.sent_id)  # B concentrates mass
            gains.append(lb - la)
        self.assertGreater(sum(gains) / len(gains), 0.0)

    def test_viterbi_conforms(self):
        s, sk = skeleton_of("Here-sThePaper")
        best = self.b.argmax(sk)
        self.assertTrue(is_conforming(best, sk))
        tree = assignment_to_tree(sk, best)
        C = {n.cat for n in tree.iter_nodes()}
        self.assertIn("Clause", C)


class TestFitting(unittest.TestCase):
    def test_fit_increases_likelihood(self):
        train = SENTENCES[:12]
        a = ModelA.fit(train, alpha=1.0)
        b0 = ModelB(a.p_cat, a.p_edge)
        nll0 = sum(-b0.logp(make_skeleton(s.root), attested_assignment(s))
                   for s in train)
        b1 = fit_loglinear(train, iterations=8, lr=0.1)
        nll1 = sum(-b1.logp(make_skeleton(s.root), attested_assignment(s))
                   for s in train)
        self.assertLess(nll1, nll0)


class TestStructured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sa, cls.sb = fit_structured(SENTENCES, alpha=1.0)

    def test_attested_finite(self):
        # every attested tree conforms, so B (support = conforming trees)
        # must give finite probability to all 220 of them
        for s in SENTENCES:
            self.assertTrue(math.isfinite(self.sa.logp(s.root)), s.sent_id)
            self.assertTrue(math.isfinite(self.sb.logp(s.root)), s.sent_id)

    def test_violating_tree_zero(self):
        # Clause :Head -> N is not licensed by the head rule
        leaf = RNode(cat="N", edge="Flat")
        bad = RNode(cat="Clause", children=[RNode(cat="N", edge="Head",
                                                  children=[leaf])])
        self.assertFalse(self.sb.conforms(bad))
        self.assertEqual(self.sb.prob(bad), 0.0)
        self.assertGreater(self.sa.prob(bad), 0.0)  # A allows anything

    def test_subcritical_A_partition(self):
        self.assertLess(self.sa.mu, 1.0)
        Za = math.exp(self.sa._logZ)
        self.assertGreater(Za, 0.5)
        self.assertLessEqual(Za, 1.0 + 1e-9)
        self.assertTrue(20 <= self.sa._exp_size <= 60)

    def test_sample_B_conforms(self):
        rng = random.Random(7)
        for _ in range(15):
            t = self.sb.sample(rng)
            self.assertTrue(self.sb.conforms(t))
            n, _ = _tree_size(t)
            self.assertLess(n, 400)

    def test_MC_conform_rate(self):
        rng = random.Random(9)
        ok = sum(1 for _ in range(60) if self.sa.conforms(self.sa.sample(rng)))
        self.assertGreater(ok / 60, 0.0)
        self.assertLess(ok / 60, 1.0)


def _tree_size(root):
    n, d = 1, 0
    for c in root.children:
        cc, dd = _tree_size(c)
        n += cc
        d = max(d, dd + 1)
    return n, d


if __name__ == "__main__":
    unittest.main(verbosity=1)
