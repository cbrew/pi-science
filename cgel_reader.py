"""Reader for CGEL treebank files (*.cgel).

The .cgel files (Reynolds / Ahmann / Schneider style) annotate English
sentences with phrase-structure trees according to the *Cambridge Grammar of
the English Language* (Huddleston & Pullum 2002).  Each file entry has a block
of ``# key = value`` metadata lines followed by one parenthesised S-expression
-- the analysis tree.

This module provides:

* ``parse_cgel_file`` / ``parse_cgel``  -- a hand-written recursive-descent
  parser for the tree language;
* ``Sentence``, ``Node``, ``Token`` objects with typed accessors;
* surface-order utilities (``surface_events``, ``tokens``, ``reconstruct_sent``);
* gap/co-indexation resolution (``gap_links``, ``binder``, ``with_gaps_filled``);
* faithful re-printing (``pretty``) and JSON export;
* a validator (``validate_file``) that checks the trees against the
  documented invariants (tokens of the tree == the ``# sent`` line with
  ``--`` at each gap, and every gap bound in the same tree).

CLI::

    python3 cgel_reader.py cgel/*.cgel               # summary of all files
    python3 cgel_reader.py --validate cgel/*.cgel    # invariant checks
    python3 cgel_reader.py --json cgel/ewt.cgel      # JSON export
    python3 cgel_reader.py --grep "sent_id" cgel/ewt.cgel  # find & print trees

Pure standard library.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------


@dataclass
class Node:
    """A node of an analysis tree.

    ``cat``    -- category (phrase or word level), e.g. ``Clause``, ``NP``,
                  ``Nom``, ``D``, ``V_aux``, ``GAP``; fused categories such as
                  ``NP+PP`` also occur.
    ``index``  -- co-indexation label (``x``, ``y``, ...) when the node is
                  written as ``(x / CATEGORY ...)``; ``None`` otherwise.
    ``edge``   -- grammatical-function label of the incoming edge (``Head``,
                  ``Subj``, ``Comp``, ...) or ``None`` for the root.
    ``feats``  -- feature map, insertion-ordered, each key maps to the list of
                  its values (repeated features such as ``:subt`` or ``:p`` are
                  kept in order).
    ``children`` -- ordered child nodes (each an independent subtree, already
                  carrying its own ``edge`` label).
    """

    cat: str
    index: Optional[str] = None
    edge: Optional[str] = None
    feats: "Dict[str, List[str]]" = field(default_factory=dict)
    children: "List[Node]" = field(default_factory=list)
    # identity hashing: nodes are positional entities (value equality is
    # available via to_dict())
    __hash__ = object.__hash__

    # -- convenience accessors ------------------------------------------------

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """First value of feature ``key`` (or ``default`` if absent)."""
        vals = self.feats.get(key)
        return vals[0] if vals else default

    def getall(self, key: str) -> List[str]:
        return list(self.feats.get(key, ()))

    @property
    def is_gap(self) -> bool:
        """True for an empty co-indexed node ``(i / GAP)``."""
        return self.cat == "GAP" and self.index is not None

    @property
    def is_lexical(self) -> bool:
        """True if the node bears a surface token (feature ``:t``)."""
        return "t" in self.feats

    @property
    def surface(self) -> Optional[str]:
        return self.get("t")

    @property
    def lemma(self) -> Optional[str]:
        return self.get("l")

    @property
    def pos(self) -> Optional[str]:
        return self.get("xpos")

    def iter_nodes(self) -> Iterator["Node"]:
        """Depth-first traversal in file (surface) order."""
        yield self
        for child in self.children:
            yield from child.iter_nodes()

    def find(self, pred) -> Optional["Node"]:
        for n in self.iter_nodes():
            if pred(n):
                return n
        return None

    # -- output ---------------------------------------------------------------

    def pretty(self, indent: str = "    ", width: int = 0) -> str:
        """Render in the same indented S-expression style as the source files.

        ``width`` > 0 renders single-child lexical nodes on one line when they
        fit; the default (0) reproduces the one-node-per-line file style.
        """
        if not self.children and not self.feats:
            return f"({self._head()})"
        head = self._head()
        parts = []
        for fkey, vals in self.feats.items():
            for v in vals:
                parts.append(f":{fkey} {self._quote(v)}")
        if not self.children:
            return f"({head} " + " ".join(parts) + ")" if parts else f"({head})"
        lines = [f"({head}"]
        if parts:
            lines.append(indent + indent.join(parts))
        for child in self.children:
            block = child.pretty(indent, width).splitlines()
            first = block[0]
            if child.edge is not None:
                first = f":{child.edge} " + first
            lines.append(indent + first)
            for line in block[1:]:
                lines.append(indent + line)
        lines[-1] += ")"
        return "\n".join(lines)

    def compact(self) -> str:
        """One-line rendering."""
        parts = [self._head()]
        for fkey, vals in self.feats.items():
            for v in vals:
                parts.append(f":{fkey} {self._quote(v)}")
        for child in self.children:
            body = child.compact()
            if child.edge is not None:
                body = f":{child.edge} " + body
            parts.append(body)
        return "(" + " ".join(parts) + ")"

    def to_dict(self) -> dict:
        d: dict = {"cat": self.cat}
        if self.index:
            d["index"] = self.index
        if self.edge:
            d["edge"] = self.edge
        if self.feats:
            d["feats"] = {k: list(v) for k, v in self.feats.items()}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    # -- helpers ---------------------------------------------------------------

    def _head(self) -> str:
        if self.index:
            return f"{self.index} / {self.cat}"
        return self.cat

    @staticmethod
    def _quote(v: str) -> str:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Token:
    """A surface word as it appears in the tree.

    ``punct`` collects any punctuation attached to the token via ``:p``
    (usually following it in the raw text);
    ``subtokens`` lists the pieces of a multi-word token in order, each as
    ``(subp_separator, subtoken)`` where the separator may be ``None`` for the
    first piece.
    """

    node: Node
    surface: str
    lemma: Optional[str] = None
    pos: Optional[str] = None
    punct: List[str] = field(default_factory=list)
    subtokens: List[Tuple[Optional[str], str]] = field(default_factory=list)
    index: Optional[str] = None

    @property
    def id(self) -> Optional[str]:
        return self.index

    @property
    def is_gap(self) -> bool:
        return self.node.is_gap

    def __str__(self) -> str:
        return self.surface


@dataclass
class Sentence:
    """One annotated sentence: metadata comments + analysis tree."""

    sent_id: str
    sent_num: int
    text: str
    sent: str
    root: Node
    alias: Optional[str] = None
    source: str = ""  # file the sentence was read from

    # -- traversal -------------------------------------------------------------

    def tokens(self) -> List[Token]:
        """Surface tokens in file order (gap nodes are ignored here)."""
        out: List[Token] = []
        for ev in self.surface_events():
            if ev[0] == "token":
                out.append(ev[1])
        return out

    def surface_events(self) -> Iterator[Tuple[str, object]]:
        """Linear stream over the tree in file order.

        Yields ``("token", Token)`` for every lexical node and
        ``("gap", str)`` for every ``(i / GAP)`` node, exactly reproducing the
        ``# sent`` line when joined with spaces (punct dropped, gaps as ``--``).
        """
        for node in self.root.iter_nodes():
            if node.is_gap:
                yield ("gap", node.index)
                continue
            if "t" in node.feats:
                subt: List[Tuple[Optional[str], str]] = []
                subs = node.getall("subt")
                seps = node.getall("subp")
                # repeated :subp/:subt interleave as (sep, piece); the leading
                # piece has no separator.
                for k, piece in enumerate(subs):
                    sep = seps[k - 1] if k > 0 and k - 1 < len(seps) else None
                    subt.append((sep, piece))
                yield (
                    "token",
                    Token(
                        node=node,
                        surface=node.get("t", ""),
                        lemma=node.get("l"),
                        pos=node.get("xpos"),
                        punct=node.getall("p"),
                        subtokens=subt,
                        index=node.index,
                    ),
                )

    def words(self) -> List[str]:
        """The flat surface word list (punct stripped, gaps skipped)."""
        return [t.surface for t in self.tokens()]

    def total_words(self) -> int:
        """Word count of the normalized ``# sent`` line."""
        return len(re.findall(r"\S+", self.sent))

    # -- gaps & co-indexation ---------------------------------------------------

    def binders(self) -> "Dict[str, Node]":
        """Map index -> node for every indexed (non-GAP) node in the tree."""
        out: Dict[str, Node] = {}
        for n in self.root.iter_nodes():
            if n.index and not n.is_gap:
                out[n.index] = n
        return out

    def gap_links(self) -> "List[Tuple[Node, Optional[Node]]]":
        """Pairs of (gap node, binder node) for every ``(i / GAP)`` in the
        tree, in file order; binder is ``None`` if the index is unbound."""
        bind = self.binders()
        return [(n, bind.get(n.index)) for n in self.root.iter_nodes() if n.is_gap]

    def with_gaps_filled(self) -> Node:
        """Copy of the tree with every ``(i / GAP)`` node replaced by a deep
        copy of the node bound to ``i`` when one exists in the same sentence.

        Use with care: co-indexation encodes both *displacement* (fronting,
        postponement, subject-aux inversion -- the binder sits at its surface
        position and the gap at the canonical one, so substitution restores
        canonical order) and *binding without displacement* (notably relative
        clauses, where the binder is a head noun or relative pronoun and the
        gap refers back to it); substitution duplicates the latter.
        """
        bind = self.binders()

        def fill(n: Node) -> Node:
            if n.is_gap and n.index in bind:
                clone = fill(_deepcopy(bind[n.index]))  # recurse: binder copies may
                # themselves contain interior gaps (e.g. a relative-clause head)
                clone.index = None
                return clone
            return Node(
                cat=n.cat,
                index=n.index,
                edge=n.edge,
                feats={k: list(v) for k, v in n.feats.items()},
                children=[fill(c) for c in n.children],
            )

        return fill(self.root)

    # -- output ------------------------------------------------------------------

    def pretty(self, width: int = 0) -> str:
        return self.root.pretty(width=width)

    def to_dict(self) -> dict:
        d = {
            "sent_id": self.sent_id,
            "sent_num": self.sent_num,
            "text": self.text,
            "sent": self.sent,
            "tree": self.root.to_dict(),
        }
        if self.alias:
            d["alias"] = self.alias
        return d


@dataclass
class Corpus:
    """A collection of sentences parsed from one or more .cgel files."""

    sentences: List[Sentence]

    def __iter__(self) -> Iterator[Sentence]:
        return iter(self.sentences)

    def __len__(self) -> int:
        return len(self.sentences)

    @classmethod
    def load(cls, paths: Sequence[str]) -> "Corpus":
        sents: List[Sentence] = []
        for path in paths:
            sents.extend(parse_cgel_file(path))
        return cls(sents)

    def to_dict(self) -> dict:
        return {"sentences": [s.to_dict() for s in self.sentences]}


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

_CAT_CHARS = re.compile(r"[A-Za-z0-9_+.-]+")
_INDEX_CHARS = re.compile(r"[A-Za-z0-9_]+")
_META_KEY = re.compile(r"^#\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse_cgel(text: str, source: str = "") -> List[Sentence]:
    """Parse the whole content of a .cgel file into ``Sentence`` objects.

    Entries are separated by blank lines; a ``# key = value`` header is
    followed by a single top-level tree.
    """
    sentences: List[Sentence] = []
    cur_meta: Dict[str, str] = {}
    tree: List[str] = []
    in_tree = False

    def flush() -> None:
        nonlocal cur_meta, tree
        if tree:
            body = "\n".join(tree)
            root = _parse_tree(body, source=source)
            sentences.append(
                Sentence(
                    sent_id=cur_meta.get("sent_id", "?"),
                    sent_num=int(cur_meta["sent_num"]) if "sent_num" in cur_meta else -1,
                    text=cur_meta.get("text", ""),
                    sent=cur_meta.get("sent", ""),
                    root=root,
                    alias=cur_meta.get("alias"),
                    source=source,
                )
            )
        cur_meta, tree = {}, []

    for line in text.splitlines():
        if line.startswith("# "):
            m = _META_KEY.match(line)
            if m:
                cur_meta[m.group(1)] = m.group(2)
        elif line.strip().startswith("("):
            in_tree = True
            tree.append(line)
        elif line.strip() == "":
            if in_tree:
                flush()
                in_tree = False
        elif in_tree:
            tree.append(line)
    if in_tree:
        flush()
    return sentences


def parse_cgel_file(path: str) -> List[Sentence]:
    return parse_cgel(Path(path).read_text(encoding="utf-8"), source=str(path))


def _parse_tree(text: str, source: str = "") -> Node:
    """Parse a single top-level S-expression (the whole string is the tree)."""

    def raiser(pos: int, msg: str) -> ValueError:
        snippet = text[max(0, pos - 40) : pos + 40].replace("\n", " ")
        return ValueError(f"{source}: {msg} near ...{snippet}...")

    def skip_space(i: int) -> int:
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        return i

    def read_token(i: int, pattern: "re.Pattern[str]") -> Tuple[str, int]:
        m = pattern.match(text, i)
        if not m:
            raise raiser(i, f"malformed token at column {i}")
        return m.group(0), m.end()

    def parse_node(i: int, depth: int = 0) -> Tuple[Node, int]:
        i = skip_space(i)
        if i >= len(text) or text[i] != "(":
            raise raiser(i, "expected '('")
        i += 1
        i = skip_space(i)
        cat, i = read_token(i, _CAT_CHARS)
        index = None
        i = skip_space(i)
        if i < len(text) and text[i] == "/":
            index = cat
            i = skip_space(i + 1)
            cat, i = read_token(i, _CAT_CHARS)
        node = Node(cat=cat, index=index)
        while True:
            i = skip_space(i)
            if i >= len(text):
                raise raiser(i, "unterminated node")
            c = text[i]
            if c == ")":
                return node, i + 1
            if c == "(":
                child, i = parse_node(i, depth + 1)
                node.children.append(child)
            elif c == ":":
                key, i = read_token(i + 1, re.compile(r"[A-Za-z0-9_+/-]+"))
                i = skip_space(i)
                if i < len(text) and text[i] == '"':
                    val, i = read_string(i)
                    node.feats.setdefault(key, []).append(val)
                elif i < len(text) and text[i] == "(":
                    child, i = parse_node(i, depth + 1)
                    child.edge = key
                    node.children.append(child)
                else:
                    raise raiser(i, f"expected string or node after ':{key}'")
            else:
                raise raiser(i, f"unexpected character {c!r}")
        raise raiser(i, "unreachable")

    def read_string(i: int) -> Tuple[str, int]:
        """Read a double-quoted string starting at the opening quote; handles
        backslash escapes (\" \\)."""
        assert text[i] == '"'
        i += 1
        buf: List[str] = []
        while i < len(text):
            c = text[i]
            if c == "\\":
                if i + 1 >= len(text):
                    raise raiser(i, "dangling backslash in string")
                buf.append(text[i + 1])
                i += 2
            elif c == '"':
                return "".join(buf), i + 1
            else:
                buf.append(c)
                i += 1
        raise raiser(i, "unterminated string")

    root, end = parse_node(0)
    rest = text[end:].strip()
    if rest:
        raise ValueError(f"{source}: trailing content after tree: {rest[:60]!r}")
    return root


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def reconstruct_sent(sentence: Sentence) -> str:
    """Rebuild the ``# sent`` line from the tree: surface tokens joined by
    spaces, ``--`` at each gap position, punctuation dropped."""
    pieces: List[str] = []
    for kind, val in sentence.surface_events():
        if kind == "token":
            pieces.append(val.surface)
        else:
            pieces.append("--")
    return " ".join(pieces)


def validate_sentence(sentence: Sentence) -> List[str]:
    """Check documented invariants; return a list of problem descriptions
    (empty list = ok).

    Invariants:
      1. tree tokens + gap markers reconstruct the ``# sent`` line verbatim;
      2. every gap index is bound (an indexed non-GAP node with that label
         exists in the same tree);
      3. every index is attached to at least one node.
    """
    issues: List[str] = []
    got = reconstruct_sent(sentence)
    if got != sentence.sent:
        issues.append(
            f"{sentence.sent_id}: sent mismatch\n"
            f"    tree  : {got}\n"
            f"    # sent: {sentence.sent}"
        )
    binders = sentence.binders()
    for n in sentence.root.iter_nodes():
        if n.is_gap and n.index not in binders:
            issues.append(f"{sentence.sent_id}: unbound gap {n.index!r}")
    used = {n.index for n in sentence.root.iter_nodes() if n.index}
    for idx in binders:
        if idx not in used:
            issues.append(f"{sentence.sent_id}: orphan index {idx!r}")
    return issues


def validate_file(path: str, verbose: bool = True) -> List[str]:
    issues: List[str] = []
    sents = parse_cgel_file(path)
    for s in sents:
        issues.extend(validate_sentence(s))
    if verbose:
        print(f"{path}: {len(sents)} sentences, {len(issues)} issue(s)")
        if issues and len(issues) <= 10:
            for msg in issues:
                print("  " + msg)
        elif issues:
            print("  (first 10 of %d)" % len(issues))
            for msg in issues[:10]:
                print("  " + msg)
    return issues


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _deepcopy(node: Node) -> Node:
    return Node(
        cat=node.cat,
        index=node.index,
        edge=node.edge,
        feats={k: list(v) for k, v in node.feats.items()},
        children=[_deepcopy(c) for c in node.children],
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read CGEL treebank files (.cgel)")
    ap.add_argument("files", nargs="+", help=".cgel file(s)")
    ap.add_argument(
        "--validate", action="store_true", help="check invariants (tokens vs # sent, gap binding)"
    )
    ap.add_argument("--json", action="store_true", help="dump corpus as JSON")
    ap.add_argument(
        "--grep", metavar="SUBSTR", default=None,
        help="print sentences whose sent_id contains SUBSTR",
    )
    ap.add_argument("--one-line", action="store_true", help="compact node rendering")
    args = ap.parse_args(argv)

    corpus = Corpus.load(args.files)
    if args.validate:
        n_issues = 0
        for path in args.files:
            n_issues += len(validate_file(path))
        print(f"total: {len(corpus)} sentences, {n_issues} issue(s)")
        return 0 if n_issues == 0 else 1
    if args.json:
        print(json.dumps(corpus.to_dict(), ensure_ascii=False, indent=2))
        return 0
    for s in corpus.sentences:
        if args.grep and args.grep not in s.sent_id:
            continue
        print(f"# sent_id = {s.sent_id}")
        print(f"# sent_num = {s.sent_num}")
        if s.alias:
            print(f"# alias = {s.alias}")
        print(f"# text = {s.text}")
        print(f"# sent = {s.sent}")
        print(s.pretty() if not args.one_line else s.root.compact())
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
