#!/usr/bin/env python3
"""Tests for Model B over the chart (cgel_coordgap_fit.py).
Run:  python3 tests/cgel_coordgap_fit.test.py
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import parse_cgel_file
import cgel_coordgap as P
from cgel_coordgap_fit import (fit, gold_features, gold_score, gradient_check,
                               inside, loglik, outside)

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]


def find(sub):
    return next(s for s in SENTENCES if sub in s.sent)


class TestInsideOutside(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = P.build_grammar(SENTENCES)

    def test_inside_dominates_viterbi(self):
        for sub in ("help me prepare lunch", "would this -- be fine",
                    "what a remarkable claim to make --"):
            s = find(sub)
            pr = P.parse(self.g, P.sentence_tokens(s), P.sentence_words(s))
            logZ = inside(self.g, s).log_inside()
            self.assertGreaterEqual(logZ, pr.logp - 1e-9, sub)

    def test_one_token_partition_by_hand(self):
        # a single N: every projection C of N with both stop features,
        # Z = sum_C P(C|N) stop_L(C) stop_R(C)
        g = self.g
        ch = P.Chart(g, ["N"], mode="sum").run()
        by_hand = sum(math.exp(g.w[("proj", "N", C)] + g.w[("stop", C, "L")]
                               + g.w[("stop", C, "R")])
                      for C in g.proj["N"] if C != "<leaf>"
                      and ("stop", C, "L") in g.w and C in P.ROOT_CATS)
        self.assertAlmostEqual(ch.log_inside(), math.log(by_hand), places=9)

    def test_expectations_match_finite_differences(self):
        for sub in ("help me prepare lunch", "would this -- be fine"):
            for f, e, fd in gradient_check(self.g, find(sub), nfeat=6):
                self.assertAlmostEqual(e, fd, places=3, msg=(sub, f))

    def test_expectations_sum_to_structure_counts(self):
        # every analysis of an n-token string has exactly one "stop" per
        # side per head: E[sum of stop features] is twice the number of
        # head tokens, i.e. 2 * (tokens that are not markers or leaves)
        # ... except that a token used as a bare leaf dependent is not a
        # head, so E[stops] + 2 E[leaves] = 2 * tokens
        s = find("help me prepare lunch")
        logZ, ex = outside(inside(self.g, s, record=True))
        stops = sum(v for f, v in ex.items() if f[0] == "stop")
        leaves = sum(v for f, v in ex.items() if f[0] == "leaf")
        self.assertAlmostEqual(stops + 2 * leaves, 2 * 4, places=6)

    def test_gold_is_an_analysis_of_the_chart(self):
        # where the Viterbi parse has every dependency right, its score is
        # the gold feature score (the gold analysis is in the support and
        # is scored by the same features)
        g = self.g
        checked = 0
        for s in SENTENCES:
            if len(P.sentence_tokens(s)) > 10:
                continue
            c = gold_features(s, g)
            if c is None:
                continue
            pr = P.parse(g, P.sentence_tokens(s), P.sentence_words(s))
            gd, pd = P.dependencies(s.root), P.dependencies(pr.tree)
            if gd == pd and pr.root_cat == s.root.cat:
                self.assertAlmostEqual(pr.logp, gold_score(c, g), places=6, msg=s.sent)
                checked += 1
            self.assertLessEqual(gold_score(c, g), inside(g, s).log_inside() + 1e-6, s.sent)
        self.assertGreaterEqual(checked, 3)

    def test_fitting_raises_the_conditional_likelihood(self):
        g = P.build_grammar(SENTENCES)
        train = [s for s in SENTENCES if len(P.sentence_tokens(s)) <= 8]
        before = [loglik(g, s) for s in train]
        h = fit(g, train, epochs=3, lr=0.05, l2=0.1, verbose=False)
        after = [loglik(g, s) for s in train]
        b = sum(x for x in before if x is not None)
        a = sum(x for x in after if x is not None)
        self.assertGreater(a, b)
        self.assertEqual(h["n"], sum(1 for x in before if x is not None))


if __name__ == "__main__":
    unittest.main(verbosity=1)
