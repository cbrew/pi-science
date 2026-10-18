#!/usr/bin/env python3
"""Tests for cgel_reader.py.

Run from the repo root:

    python3 tests/cgel_reader.test.py
    # or
    python3 -m unittest tests.cgel_reader.test -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgel_reader import (  # noqa: E402
    Corpus,
    Node,
    _parse_tree,
    parse_cgel_file,
    reconstruct_sent,
    validate_sentence,
)

CGEL = Path(__file__).resolve().parent.parent / "cgel"
FILES = ["ewt.cgel", "ewt-test_iaa50.cgel", "ewt-test_pilot5.cgel", "twitter.cgel"]
EXPECTED_COUNTS = {"ewt.cgel": 100, "ewt-test_iaa50.cgel": 50,
                   "ewt-test_pilot5.cgel": 5, "twitter.cgel": 65}


class TestParsing(unittest.TestCase):
    def test_sentence_counts(self):
        for fn in FILES:
            with self.subTest(fn=fn):
                self.assertEqual(len(parse_cgel_file(str(CGEL / fn))),
                                 EXPECTED_COUNTS[fn], fn)

    def test_metadata(self):
        s = parse_cgel_file(str(CGEL / "ewt-test_pilot5.cgel"))[0]
        self.assertEqual(s.sent_id, "answers-20111106022931AAwpqXm_ans-0001")
        self.assertEqual(s.sent_num, 1)
        self.assertEqual(s.text, "NZers: Have you decided who you're going to vote for?")
        self.assertEqual(s.sent, "NZers have you -- decided who you 're going to vote for --")
        self.assertIsNone(s.alias)  # pilot5 has no # alias lines
        self.assertEqual(s.root.cat, "Clause")
        # ewt.cgel carries provenance to the original CGELbank .tex trees
        e = parse_cgel_file(str(CGEL / "ewt.cgel"))[0]
        self.assertEqual(e.alias, "trees/TrainingSet1 2/001.tex")
        # no alias on twitter sentences
        t = parse_cgel_file(str(CGEL / "twitter.cgel"))[0]
        self.assertIsNone(t.alias)

    def test_tree_structure(self):
        s = parse_cgel_file(str(CGEL / "ewt-test_pilot5.cgel"))[0]
        voc = s.root.children[0]
        self.assertEqual(voc.edge, "Vocative")
        self.assertEqual(voc.cat, "NP")
        self.assertEqual(voc.children[0].cat, "Nom")
        n = voc.children[0].children[0]
        self.assertEqual((n.cat, n.edge), ("N", "Head"))
        self.assertEqual(n.get("t"), "NZers")
        self.assertEqual(n.get("l"), "NZer")
        self.assertEqual(n.getall("p"), [":"])
        # root has no edge
        self.assertIsNone(s.root.edge)


class TestSurface(unittest.TestCase):
    def test_reconstruct_sent_matches_header(self):
        """For every sentence, tree tokens + gap markers == the # sent line."""
        for fn in FILES:
            for s in parse_cgel_file(str(CGEL / fn)):
                with self.subTest(fn=fn, sent_id=s.sent_id):
                    self.assertEqual(reconstruct_sent(s), s.sent)

    def test_validation_clean(self):
        for fn in FILES:
            for s in parse_cgel_file(str(CGEL / fn)):
                with self.subTest(fn=fn, sent_id=s.sent_id):
                    self.assertEqual(validate_sentence(s), [])

    def test_tokens_and_gaps(self):
        s = [x for x in parse_cgel_file(str(CGEL / "twitter.cgel"))
             if "Here-sThePaper" in x.sent_id][0]
        self.assertEqual(
            [t.surface for t in s.tokens()],
            ["here", "'s", "the", "paper", "that", "people", "who", "read",
             "it", "will", "find", "out", "about", "how", "resumptive",
             "pronouns", "help", "islands", "go", "down", "a little", "easier"],
        )
        gaps = [(g.index, b.cat if b else None) for g, b in s.gap_links()]
        self.assertEqual(gaps, [("b", "NP"), ("a", "PP"), ("y", "NP"), ("z", "AdvP")])


class TestDetails(unittest.TestCase):
    def test_gap_filling(self):
        s = [x for x in parse_cgel_file(str(CGEL / "twitter.cgel"))
             if "Here-sThePaper" in x.sent_id][0]
        filled = s.with_gaps_filled()
        self.assertEqual([n for n in filled.iter_nodes() if n.is_gap], [])
        self.assertTrue(any(n.surface == "a little" for n in filled.iter_nodes()))

    def test_multiword_tokens(self):
        s = parse_cgel_file(str(CGEL / "ewt-test_pilot5.cgel"))[3]  # "in case ..."
        ice = [n for n in s.root.iter_nodes()
               if n.surface == "in case"][0]
        self.assertEqual(ice.cat, "P")
        self.assertEqual(ice.get("l"), "in")
        self.assertEqual(ice.getall("subt"), ["In", "case"])
        one = s.tokens()[0]
        self.assertEqual(one.surface, "in case")
        self.assertEqual(one.subtokens, [(None, "In"), (None, "case")])

    def test_subp_separator(self):
        # find any token with a :subp separator between sub-tokens
        for s in parse_cgel_file(str(CGEL / "ewt.cgel")):
            for t in s.tokens():
                seps = [sep for sep, _ in t.subtokens if sep is not None]
                if seps:
                    self.assertEqual(t.surface, "test-drive")
                    self.assertEqual(t.subtokens,
                                     [(None, "test"), ("-", "drive")])
                    return
        raise AssertionError("no :subp token found")

    def test_escaped_quotes_and_utf8(self):
        found_punct_quote = found_rel = False
        for fn in FILES:
            for s in parse_cgel_file(str(CGEL / fn)):
                for n in s.root.iter_nodes():
                    if '"' in n.getall("p"):
                        found_punct_quote = True
                    if n.get("t") and any(ord(ch) > 127 for ch in n.get("t")):
                        found_rel = True
        self.assertTrue(found_punct_quote, "expected some \"\" punctuation")
        self.assertTrue(found_rel, "expected some non-ASCII tokens")

    def test_empty_value(self):
        # empty annotation values must parse (e.g. :correct "")
        for fn in FILES:
            for s in parse_cgel_file(str(CGEL / fn)):
                for n in s.root.iter_nodes():
                    if "correct" in n.feats and n.get("correct") == "":
                        return
        raise AssertionError("no empty :correct value found")

    def test_roundtrip_pretty_and_compact(self):
        for fn in FILES:
            for s in parse_cgel_file(str(CGEL / fn)):
                with self.subTest(fn=fn, sent_id=s.sent_id, mode="pretty"):
                    self.assertEqual(_parse_tree(s.pretty()).to_dict(), s.root.to_dict())
                with self.subTest(fn=fn, sent_id=s.sent_id, mode="compact"):
                    self.assertEqual(_parse_tree(s.root.compact()).to_dict(), s.root.to_dict())

    def test_indexed_lexical_node(self):
        s = [x for x in parse_cgel_file(str(CGEL / "twitter.cgel"))
             if "IsThatWhatYouCall" in x.sent_id][0]
        fronted = s.root.children[0]
        self.assertEqual((fronted.index, fronted.cat, fronted.edge), ("x", "V_aux", "Prenucleus"))
        self.assertEqual(fronted.get("t"), "is")
        gap = [n for n in s.root.iter_nodes() if n.is_gap]
        self.assertEqual([g.index for g in gap], ["x", "y"])

    def test_json_export(self):
        s = parse_cgel_file(str(CGEL / "ewt-test_pilot5.cgel"))[0]
        d = s.to_dict()
        self.assertEqual(d["sent_id"], s.sent_id)
        self.assertEqual(d["tree"]["cat"], "Clause")
        self.assertTrue(all(isinstance(c["edge"], str) for c in d["tree"]["children"]))
        # JSON-serializable
        json.dumps(d, ensure_ascii=False)
        self.assertEqual(len(json.loads(json.dumps(s.to_dict()))["tree"]["children"]),
                         len(s.root.children))


if __name__ == "__main__":
    unittest.main(verbosity=2)