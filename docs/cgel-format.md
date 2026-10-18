# The CGEL treebank format (`*.cgel`)

This note describes what the `.cgel` files in `cgel/` represent and how the tree
language works. It accompanies `cgel_reader.py`, a reader/parser for the format.

## Background

The trees are sentence analyses in the syntactic framework of the *Cambridge
Grammar of the English Language* (CGEL; Huddleston & Pullum 2002). Unlike
dependency or the dominant phrase-structure schools, CGEL is a
**constituent ("phrase-structure") grammar whose key relations are between
functions** (subject, object, complement, modifier) and heads, with a rich
inventory of clause constructions (extraposition, prenucleus fronting,
existential clauses, fused determiner-heads, coordination of unlike
categories, etc.).

The treebank is the CGEL treebank of Reynolds, Ahmann ("Ahmani") and Schneider
(also distributed under the name *EWT-CGEL*): the analyses are annotated in a
compact parenthesised notation derived from Reynolds' *CGELbank* tree set, and
the sentences come from the English Web Treebank (EWT) and the Twitter treebank.

### The files in `cgel/`

| file                | sentences | content                                             |
|---------------------|-----------|-----------------------------------------------------|
| `ewt.cgel`          | 100       | EWT sentences (training subset); each carries a `# alias` to the original CGELbank `.tex` tree (e.g. `trees/TrainingSet1 2/001.tex`) |
| `ewt-test_iaa50.cgel` | 50     | EWT test subset (inter-annotator agreement)         |
| `ewt-test_pilot5.cgel` |  5     | pilot trees (with `# alias` provenance)             |
| `twitter.cgel`      | 65        | tweets (ids like `Tree TheFutureOfLinguistics-0`)   |

220 sentences in total. Files are UTF-8, one sentence per blank-line-separated
entry.

## Anatomy of an entry

```
# sent_id = reviews-020992-0003          <- source-corpus sentence id
# sent_num = 1                          <- order within the file
# alias = trees/TrainingSet1 2/001.tex  <- provenance (optional)
# text = At 3:15 am ... strobe light activated in my room.
# sent = at 3:15 am on night # 2 the fire alarm and strobe light activated in my room
(Clause
    :Mod (PP
        :Head (P :t "at")
        ...
```

* **`# text`** — the raw sentence exactly as it appears in the source corpus
  (original casing and punctuation).
* **`# sent`** — the normalized analysis sentence the tree is aligned to:
  lower-cased, punctuation removed (folded into the tokens' `:p` feature), and
  EWT-style tokenization applied (`Here's` → `here 's` as two tokens). It is
  exactly the sequence of surface tokens in the tree, in file order, with a
  `--` marker inserted at every gap (see below) and spaces between tokens.
* **the tree** — one parenthesized S-expression root per sentence.

## The tree language

Every node is written

```
( CATEGORY  [index /]  :feature "value" ...  :function (child) ... )
```

* **Category.** Phrase-level or word-level category, e.g. `Clause`, `NP`,
  `Nom`, `VP`, `D`, `V_aux`. Categories may fuse with `+` (`NP+PP`) where a
  single constituent realizes two categories at once.
* **Index.** *Optional* `x /` prefix before the category: `(x / NP ...)` marks
  a co-indexation. `(x / GAP)` (category `GAP`, no children) is an **empty gap**
  bound to index `x`.
* **Features.** `:key "value"` pairs; a key may repeat (`:subt`, `:p`).
  Values are double-quoted with `\"` and `\\` escapes; UTF-8 is allowed.
* **Children.** Each child carries a `:function` role (the *grammatical
  function* of that constituent), then a recursive node.

Formatting is significant only through parentheses — indentation is cosmetic
(4 spaces per level in the source files).

### Categories

Phrase-level (with counts across the 4 files):

| category | count | role |
|----------|------:|------|
| `Clause` | 774 | finite and non-finite clauses |
| `Clause_rel` | 96 | relative clauses |
| `VP` | 986 | verb phrase (the clausal head) |
| `NP` | 1144 | noun phrase |
| `Nom` | 1415 | nominal (NP without the determiner) |
| `DP` | 387 | determinative phrase |
| `PP` | 426 | prepositional phrase |
| `AdjP` / `AdvP` / `IntP` | 244 / 162 / 6 | adjective / adverb / interjection phrase |
| `Coordination` | 131 | coordination (conjuncts = `:Coordinate`) |
| `GAP` | 119 | empty co-indexed node (always with an index) |

Word-level (lexical heads):

| category | count | CGEL word class |
|----------|------:|-----------------|
| `N` | 945 | noun |
| `N_pro` | 325 | pronoun |
| `V` | 441 | verb |
| `V_aux` | 276 | auxiliary verb (incl. modals, *be*, *have*, *do*) |
| `P` | 415 | preposition |
| `D` | 389 | determinative |
| `Adj` / `Adv` | 221 / 161 | adjective / adverb |
| `Coordinator` | 133 | coordinator (*and*, *but*, *or*, …) |
| `Sdr` | 122 | subordinator (*that*, *to*, *whether*, *if*, …) |
| `Int` | 6 | interjection |
| `PP_strand` | 4 | stranded preposition (*from* in "treatments to choose **from**") |

Fused categories: `NP+PP` (6), `NP+AdvP` (3), `NP+Clause` (2), `NP+AdjP` (1) —
used chiefly for coordination of constituents of unlike categories that still
need a single label ("my initial selection satisfactory" is simultaneously the
object and the predicative complement of *found*).

### Grammatical functions (edge labels)

`Head` is by far the most common (5566). The others, in order:

| function | count | meaning (CGEL) |
|----------|------:|----------------|
| `Mod` | 767 | modifier (pre- or post-head) |
| `Obj` | 502 | object (direct unless specified) |
| `Comp` | 496 | complement (of a verb or preposition) |
| `Det` | 374 | determiner within NP |
| `Subj` | 368 | subject |
| `Coordinate` | 275 | conjunct in a coordination |
| `Marker` | 255 | marker (subordinator/coordinator serving as clause marker) |
| `Supplement` | 113 | supplement: apposition, dislocated/adjunct-like material |
| `PredComp` | 107 | predicative complement |
| `Flat` | 86 | flat structure for proper names / number+unit ("Flat" items of a single name or measure) |
| `Det-Head` | 66 | fused determinative-head ("one", "that", "another", "200") |
| `Prenucleus` | 55 | fronted (pre-nuclear) constituent |
| `Postnucleus` | 14 | postponed constituent |
| `DisplacedSubj` | 10 | displaced subject in existential clauses ("there **is** *something* wrong") |
| `Comp_ind` | 9 | indirect-object-like complement (ditransitive with *give*, ...) — also `Obj_ind` (8) / `Obj_dir` (8) |
| `Particle` | 9 | verb particle ("find *out*") |
| `ExtraposedSubj` | 7 | extraposed subject ("it will be hard *to keep his weight up*") |
| `Vocative` | 4 | vocative (direct address) |
| `Compounding` | 4 | compound formation ("oil-producing", "paper **making**") |
| `Mod-Head` | 6 | constituent that is simultaneously modifier of and head of (coordination context) |
| `Head-Prenucleus` | 6 | constituent that is simultaneously head and fronted (e.g. relative "what") |
| `Obj+Mod` | 3 | fused object+modifier (a few "since then") |
| `Marker-Head` | 1 | fused marker+head ("etc.") |
| `Obj+PredComp/Comp` | 1 | fused object+predicative complement, also the complement |

Fused function labels joined by `+` (or `+.../...` like
`:Obj+PredComp/Comp`) mean one constituent realizes several functions at once.

### Features

| feature | count | meaning |
|---------|------:|---------|
| `:t` | 3390 | surface token (the word as written; multi-word tokens such as `"in case"` or `"a little"` are single `:t` values) |
| `:xpos` | 783 | Penn Treebank POS tag, carried over from the source EWT data (`VB`, `VBZ`, `MD`, `CD`, `LS`, …) — mostly on verbs, auxiliaries and numerals |
| `:l` | 688 | lemma/lexeme (e.g. `:t "can't" :l "can"`, `:t "'s" :l "be"`) |
| `:p` | 381 | punctuation attached to the token (dropped from `# sent`): `.`, `,`, `?`, `"`, `(`, `)`, `-`, `...`, `—`, `--`, … |
| `:subt` | 120 | sub-token pieces of a multi-word token (repeatable) |
| `:note` | 42 | annotator note (often a CGEL page reference, or a flag such as "TODO: flat?") |
| `:correct` | 22 | corrected spelling (tree keeps the original surface, `:l` and `:correct` give the intended form, e.g. `:t "ideolect" :correct "idiolect"`) |
| `:subp` | 9 | separator between sub-tokens (e.g. `-` in `test-drive` → `:subt "test" :subp "-" :subt "drive"`) |

## Co-indexation, gaps and displacement

An indexed node `(x / CATEGORY ...)` is a constituent that is *also* referred to
from elsewhere. A node `(x / GAP)` marks one of those reference positions as an
**empty gap**. Two uses coexist (the annotation does not distinguish them
formally):

1. **Displacement** — the binder sits at its *surface* position and the gap at
   the *canonical* position it would occupy in a basic clause.
   Surface order is preserved by the file layout, so the surface sentence can be
   read directly off the tree (see the invariant below).
   - subject–auxiliary inversion: `:Prenucleus (x / V_aux :t "is" ...)` with
     `:Head (x / GAP)` in the VP (*Is* that what you call…);
   - prenucleus fronting: `:Prenucleus (x / PP :Head (P :t "here"))` with the
     gap in the predicate of *be* (Here's the paper …; *here* is the predicate
     complement, *the paper* the postposed subject — both displaced);
   - postponement: `:Postnucleus (y / NP ...)` with `:Subj (y / GAP)`.
2. **Binding without movement** — especially in relative clauses, where the
   binder is a head noun (or relative pronoun) in its canonical position and
   the gap is the position it binds inside the relative clause (… "treatments"
   we have *sent* `(z / GAP)`).

Index labels are single letters chosen per sentence (`x`, `y`, `z`, sometimes
`i`, `j`, `a`, `b`); they are **not** corpus-global. Every gap used in these
files is bound to a binder within the same tree.

Because `# sent` inserts exactly one `--` per gap node, the two are mutually
validating: reading the tree linearly (tokens + gap markers) reproduces
`# sent` character-for-character, and that invariant is checked by
`cgel_reader.py --validate` (it holds for all 220 sentences).

## Tree shape and CGEL constructions in practice

* **Clauses.** A `Clause` typically has `Subj` + a `VP` head (`Head`); the VP
  head is the verb (with `V_aux` for auxiliaries), followed by `Comp`, `Obj`,
  `PredComp`, `Mod`. Non-finite clauses headed by `VP` also occur
  ("to vote" → `Clause :Head (VP :Marker (Sdr :t "to") :Head (VP …))`).
* **Subject-predicate inversion**, **existentials** ("there is" with
  `DisplacedSubj`), **extraposition** (`it … <to-VP>` with `ExtraposedSubj`),
  **relative clauses** (`Clause_rel` with optional `:Marker (Sdr :t "that")`
  and/or a `Prenucleus`/`Head-Prenucleus` operator) all appear as first-class
  structures.
* **Coordination** is a `Coordination` node with `:Coordinate` conjuncts;
  non-initial conjuncts carry `:Marker (Coordinator …)`. Conjuncts may be of
  unlike categories; the node then gets a fused category (`NP+PP`, …) and its
  edge a fused function (`Obj+Mod`).
* **Determiners** appear either as `:Det (DP :Head (D …))`, as bare
  `:Det (NP …)` when the determiner is a genitive pronoun ("my"), or fused as
  `:Det-Head (DP :Head (D …))` for *one, that, another, …*.
* **Proper names** use `:Flat` items, e.g. `(Nom :Flat (N :t "Kofi") :Flat (N :t "Annan"))`.

## Known quirks

* Annotator typos are preserved in `:t` and flagged with `:correct`
  (`superintendant → superintendent`), and `:l` reflects the corrected form.
* Some tokens carry embedded punctuation inside `:t` (e.g. `"etc."`, `"3:15"`);
  the `.` only shows up as `:p` *between* tokens.
* `:correct ""` and odd tokens (`"$ometime$"` for *sometimes*) occur; the trees
  are human annotations, not clean automated output.

## Reading the trees

Use `cgel_reader.py` (pure stdlib, Python 3):

```sh
python3 cgel_reader.py cgel/*.cgel                     # overview print
python3 cgel_reader.py --validate cgel/*.cgel          # invariant checks
python3 cgel_reader.py --json cgel/ewt.cgel            # JSON dump
python3 cgel_reader.py --grep "Here-sThePaper" cgel/twitter.cgel
```

Programmatic API — see the module docstring for details:

```python
from cgel_reader import Corpus

corpus = Corpus.load(["cgel/ewt.cgel", "cgel/twitter.cgel"])
for s in corpus:
    for tok in s.tokens():
        print(tok.surface, tok.lemma, tok.pos, tok.punct)
    for gap, binder in s.gap_links():      # gap resolution
        ...
    print(s.root.pretty())                  # re-print like the source
    s.with_gaps_filled()                    # substitute binders at gap sites
```

## See also

* [`cgel-conventions.md`](cgel-conventions.md) — how the function labels
  (edges) and constituent labels (categories) are coupled: the X-bar/projection
  skeleton and the head rule, with verified tables of what may dominate what
  and what may realise each function.
* [`cgel-models.md`](cgel-models.md) — two probability models over the
  analyses: Model A (labels independent) and Model B (convention-conforming
  analyses only), plus generative structural models that also score tree shape.
* [`cgel-splithead.md`](cgel-splithead.md) — a bottom-up, head-driven
  (Eisner split-head) generative model built from words/POS, properly
  normalised with no partition function or depth bound.
* `cgel_conventions.py` — mechanical checker for those conventions.
* `cgel_grammar.py` — the conventions as machine-readable tables (the license
  set used by the models).