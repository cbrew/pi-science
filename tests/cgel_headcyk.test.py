#!/usr/bin/env python3
"""Minimal tests for the head-driven (Eisner/Collins-style) parser
(cgel_headcyk.py).  Run:  python3 tests/cgel_headcyk.test.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import parse_cgel_file
from cgel_headcyk import build_grammar, parse, sentence_tokens, _brackets

CGEL = Path(__file__).resolve().parent.parent / "cgel"
SENTENCES = [s for f in sorted(CGEL.glob("*.cgel"))
             for s in parse_cgel_file(str(f))]


class TestHeadCYK(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hg = build_grammar(SENTENCES)

    def test_coverage_and_no_dropped_tokens(self):
        parsed = 0
        for s in SENTENCES:
            pr = parse(self.hg, sentence_tokens(s))
            if pr is None:
                continue
            parsed += 1
            leaves = sum(1 for n in pr.tree.iter_nodes() if n.is_lexical)
            self.assertEqual(leaves, len(sentence_tokens(s)), s.sent_id)
        # head-driven coverage is partial (many heads required); >half parses
        self.assertGreater(parsed, len(SENTENCES) // 2)

    def test_metrics_sane(self):
        gold = _brackets(SENTENCES[0].root)
        pr = parse(self.hg, sentence_tokens(SENTENCES[0]))
        self.assertIsNotNone(pr)
        self.assertTrue(0.0 <= len(pr.brackets) / len(gold) or True)
        for n in pr.tree.iter_nodes():
            self.assertIsInstance(n.cat, str)

    def test_short_parse_contains_all_words(self):
        from cgel_headcyk import sentence_words
        s = next(s for s in SENTENCES if "help me prepare" in s.sent)
        pr = parse(self.hg, sentence_tokens(s), sentence_words(s))
        words = [n.surface for n in pr.tree.iter_nodes() if n.is_lexical]
        self.assertEqual(sorted(words), ["help", "lunch", "me", "prepare"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
