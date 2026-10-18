#!/usr/bin/env python3
"""Minimal tests for the clean CYK parser (cgel_cyk.py).

Run:  python3 tests/cgel_cyk.test.py
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import parse_cgel_file
from cgel_cyk import (Grammar, Parse, collect_rules, evaluate, parse,
                      sentence_tokens, _brackets)

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]


class TestGrammar(unittest.TestCase):
    def test_self_coverage(self):
        g = Grammar(collect_rules(SENTENCES))
        parsed = sum(1 for s in SENTENCES if parse(g, sentence_tokens(s)))
        self.assertEqual(parsed, len(SENTENCES))

    def test_short_parse_wellformed(self):
        g = Grammar(collect_rules(SENTENCES))
        s = next(s for s in SENTENCES if "help me prepare" in s.sent)
        pr = parse(g, sentence_tokens(s))
        self.assertIsInstance(pr, Parse)
        # reconstructed tree must contain only real (string) categories
        for n in pr.tree.iter_nodes():
            self.assertIsInstance(n.cat, str)
            self.assertFalse(n.cat.startswith("@"))


class TestMetrics(unittest.TestCase):
    def test_metrics_sane(self):
        g = Grammar(collect_rules(SENTENCES))
        rows = evaluate(SENTENCES, g)
        self.assertTrue(all(0.0 <= r[3] <= 1.0 for r in rows))  # F1 in [0,1]
        self.assertEqual(len(rows), len(SENTENCES))

    def test_gold_exact_on_self_reference(self):
        # the gold bracketing of a sentence is present; brackets are hashable
        s = SENTENCES[0]
        self.assertTrue(len(_brackets(s.root)) > 0)
        self.assertTrue(math.isfinite(len(_brackets(s.root))))
        self.assertEqual(len(_brackets(s.root)), len(set(_brackets(s.root))))


if __name__ == "__main__":
    unittest.main(verbosity=1)
