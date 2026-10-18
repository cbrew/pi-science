# Function labels and constituent labels: the two conventions

In the CGEL treebank files the two label dimensions are **not independent**.
A tree node carries

* a **constituent label** (category): `Clause`, `VP`, `NP`, `Nom`, `D`, `N`,
  `Prenucleus` is *not* a category, etc., and
* an incoming **function label** (edge): `Head`, `Subj`, `Mod`, `Comp`, ...

The annotation is governed by two conventions that couple the dimensions:

1. the **XBAR (projection) convention** — which constituent labels may
   *dominate* which (the phrase-structure skeleton), and
2. the **head rule** — which constituent labels may realise each *function*
   label, and under which parents each function may appear.

Both are stated below as they are *instantiated by this corpus*. The tables
are induced from all 220 trees; the rules are verified by
`cgel_conventions.py` (220 sentences → 4 flagged items, each an intentional
annotator choice, see §7).

## 1. The X-bar convention: a two-level projection skeleton

Each lexical word class projects an **intermediate** phrase and — for the two
clausal/nominal families — a **maximal** phrase. Practically:

| word (head)  | intermediate  | maximal         | notes |
|--------------|---------------|-----------------|-------|
| `N` / `N_pro` | `Nom`        | `NP`            | three tiers |
| `V` / `V_aux` | `VP`         | `Clause`        | three tiers; `Clause_rel` is the relative-clause variant of `Clause` |
| `P`          | `PP`         | (—)             | PP is the maximal; recursion by `PP :Head -> PP` |
| `D`          | `DP`         | (—)             | DP appears as `:Det`/`:Det-Head` inside NP |
| `Adj`        | `AdjP`       | (—)             | |
| `Adv`        | `AdvP`       | (—)             | |
| `Int`        | `IntP`       | (—)             | |
| `Coordinator`,`Sdr` | —   | —               | function words, no own projection |

So, reading a tree bottom-up: `N → Nom → NP`, `V → VP → Clause`,
`P → PP`, `D → DP`, `Adj → AdjP`, `Adv → AdvP`, `Int → IntP`;
and top-down the **dominance** facts (children a category may directly
dominate; complete inventory, edges ignored) are:

| parent | may dominate, in practice |
|--------|---------------------------|
| `Clause` | `VP`, `Clause`, `NP`, `PP`, `AdvP`, `AdjP`, `V_aux`, `Sdr`, `Coordinator`, `Coordination`, `IntP`, `GAP` |
| `Clause_rel` | `VP`, `Clause_rel`, `NP`, `GAP`, `Sdr`, `PP` |
| `VP` | `V`, `V_aux`, `VP`, `Clause`, `NP`, `PP`, `AdvP`, `AdjP`, `Sdr`, `Coordinator`, `Coordination`, `DP`, `PP_strand`, `GAP` |
| `NP` | `Nom`, `NP`, `DP`, `Coordinator`, `Coordination`, `AdvP`, `PP`, `Clause_rel`, `Clause`, `AdjP`, `GAP` |
| `Nom` | `N`, `N_pro`, `Nom`, `AdjP`, `PP`, `DP`, `Clause_rel`, `Clause`, `VP`, `Coordinator`, `Coordination`, `NP` |
| `PP` | `P`, `NP`, `Clause`, `PP`, `Coordination`, `AdvP`, `Coordinator` |
| `DP` | `D`, `DP`, `AdvP`, `PP`, `Coordination`, `Coordinator` |
| `AdjP` | `Adj`, `AdjP`, `AdvP`, `PP`, `Coordinator`, `DP`, `Clause` |
| `AdvP` | `Adv`, `AdvP`, `DP`, `PP`, `Coordinator`, `NP` |
| `Coordination` | any coordinateable phrase or word + `Coordinator` |

Two consequences are worth spelling out:

* **`Nom` and `VP` are the bar-level categories.** They are the *only*
  intermediate projections that receive their own label; for `P`, `D`, `Adj`,
  `Adv`, `Int` the label `PP`/`DP`/`AdjP`/`AdvP`/`IntP` is used for both the
  intermediate and the maximal level, and recursion is by *same-category
  heads* (`PP :Head → PP`, `AdjP :Head → AdjP`, «off to São Paulo»,
  «old enough», …).
* **`Coordination` is transparent to projection.** A coordinate may stand
  wherever its bare conjunct could stand, and the conjuncts may be *lower*
  tiers than the context expects (`:Head (Coordination :Coordinate (Nom) …)`
  inside an NP — "the fire alarm **and** strobe light"). To label one node
  with two different projections at once, the annotation uses **fused
  categories**: `NP+PP`, `NP+AdvP`, `NP+AdjP`, `NP+Clause` (all but the last
  occur only inside `Coordination`).

## 2. The head rule

A `:Head` child is the constituent that determines the phrase type. The
convention, in full, is the following table (counts over the 220 trees):

| parent            | allowed `:Head` children (counts)                            |
|-------------------|--------------------------------------------------------------|
| `Clause`          | `VP` 609 · `Clause` 152 · `Coordination` 10 · `GAP` 3        |
| `Clause_rel`      | `VP` 57 · `Clause_rel` 39                                    |
| `VP`              | `V` 441 · `VP` 261 · `V_aux` 256 · `GAP` 19 · `Coordination` 9 |
| `NP`              | `Nom` 1088 · `NP` 46 · `Coordination` 9 · `GAP` 1            |
| `Nom`             | `N` 863 · `N_pro` 325 · `Nom` 144                            |
| `PP`              | `P` 411 · `PP` 15                                            |
| `PP_strand`       | `P` 4                                                        |
| `DP`              | `D` 385 · `DP` 1 · `Coordination` 1                          |
| `AdjP`            | `Adj` 221 · `AdjP` 23                                        |
| `AdvP`            | `Adv` 161 · `AdvP` 1                                         |
| `IntP`            | `Int` 6                                                      |
| fused `NP+X`      | itself (the node is one constituent with two labels)          |

Reading the pattern:

* **The head is the category one tier below the parent** (same "lexical
  family"): NP's head is `Nom`, Nom's head is `N`/`N_pro`, VP's head is
  `V`/`V_aux`, Clause's head is `VP`, PP's head is `P`, DP's head is `D`, …
* **Same-tier recursion is allowed**: `Clause :Head → Clause` (main-clause
  structures with an auxiliary in the prenucleus), `VP :Head → VP` (verb
  groups/coordination-like nesting), `NP :Head → NP`, `Nom :Head → Nom`,
  `PP :Head → PP`, `AdjP :Head → AdjP`, `DP :Head → DP`.
* **A coordinated head is a `Coordination` whose conjuncts are of the
  parent's lexical tier** (`Clause`, `VP`/`Nom`/`D` …); presented as
  `:Head (Coordination :Coordinate (VP…) …)`.
* **A displaced head is `GAP`** with an index whose binder is the head in its
  surface position (auxiliary inversion: `:Head (x / GAP)` bound by
  `:Prenucleus (x / V_aux …)`).

### Fused-head function labels

The treebank marks CGEL's **fused-head constructions** by splitting the
`Head` function rather than doubling labels:

| function | means | example |
|----------|-------|---------|
| `Det-Head` | fused determinative-head (CGEL §5.5) | `:Det-Head (DP :Head (D :t "one"))` — "one", "that", "another", "enough" |
| `Mod-Head` | fused modifier-head | "by far **the best**": `:Mod-Head (AdjP :Head (Adj :t "best"))`; also PP "above", VP "following" |
| `Marker-Head` | fused marker-head | "… cost center **etc.**": `:Marker-Head (Coordinator …)` |
| `Head-Prenucleus` | head that is also fronted | relative "what"/"who": `:Head-Prenucleus (x / NP …)` under `Clause_rel` |

Two further fused *function* labels resolve nodes that realise two functions
against one parent: `Obj+Mod` ("a few **since then**") and `Obj+PredComp/Comp`
("found **my initial selection satisfactory**").

## 3. Function → parent licensing

Which parents each function may attach under (complete sets, counts in
parentheses where illuminating):

| function | appears under |
|----------|---------------|
| `Head` | every non-word category (see §2) |
| `Subj` | `Clause` (319), `Clause_rel` (49) — *only clauses* |
| `Obj`, `Obj_dir`, `Obj_ind` | `VP` (and fused categories / stranded PPs for `Obj`) |
| `Comp` | `VP` (350), `PP` (69), `Nom` (64), `AdjP` (11), `Clause` (1) |
| `Comp_ind` | `Nom`, `AdjP`, `AdvP`, `Clause` ("old enough **to** …") |
| `PredComp` | `VP` (102), `PP` (4) |
| `Det` | `NP` only (374) |
| `Det-Head` | `Nom` only (66) |
| `Marker` | `VP`, `Clause`, `Clause_rel`, `NP`, `Nom`, `AdjP`, `PP`, fused — i.e. any coordinate or non-finite head (see §4/§5) |
| `Mod` | `Nom` (438), `VP` (191), `Clause` (43), `AdjP` (37), `NP` (18), `PP` (15), `AdvP` (13), `DP` (6) |
| `Supplement` | `Clause` (54), `NP` (44), `Nom` (5), `VP`, `PP`, `Coordination`, `AdjP`, `Clause_rel` |
| `Prenucleus` | `Clause` (39), `Clause_rel` (16) |
| `Postnucleus` | `Clause` (8), `VP` (4), `AdjP`, `Nom` |
| `DisplacedSubj`/`ExtraposedSubj` | `VP` only |
| `Particle` | `VP` only |
| `Vocative` | `Clause` (3), `VP` (1) |
| `Flat` | `N` (82), `D` (4) — the flat-name containers are word nodes, see §5 |
| `Compounding` | `Nom` |
| `Coordinate` | `Coordination` only |
| `Head-Prenucleus`/`Marker-Head` | `Clause_rel` / `Nom` |

## 4. Function → child licensing

Given a parent, the function also constrains *which category* the child may
be (this is the head rule quotient; the full picture needs both tables):

| function | may be realised by |
|----------|--------------------|
| `Head` | see §2 |
| `Subj` | `NP` (331), `GAP` (30), `Clause` (4), `PP` (1 — flagged with a note: "PP as subject pp. 646-647") |
| `Obj` / `Obj_dir` / `Obj_ind` | `NP`, `GAP`, `Coordination` |
| `Comp` | `Clause` (314), `PP` (155), `Coordination`, `GAP`, `PP_strand`, `AdjP`, `NP` |
| `PredComp` | `AdjP` (46), `NP` (40), `PP` (7), `Coordination`, `GAP`, `Clause` |
| `Det` | `DP` (300), `NP` (72 — genitive pronouns: "my", "our"), `PP` (2 — flagged, one with the note "PP in lieu of DP, p. 433") |
| `Marker` | `Sdr` (122), `Coordinator` (132), `DP` (2 — correlative "both"…) |
| `Prenucleus` | `V_aux` (20), `NP` (18), `AdvP` (7), `PP` (6), `AdjP` (2), `Clause`, `VP` |
| `Postnucleus` | `NP` (8), `Clause` (3), `PP` (2), `Coordination` |
| `Mod` | `PP` (187), `Nom` (145), `AdvP` (145), `AdjP` (138), `Clause_rel` (50), `GAP` (21), `NP`, `DP`, `Clause`, `Coordination`, `VP` — the open class |
| `Supplement` | `NP` (38), `PP` (33), `Clause` (14), `AdvP` (9), `Clause_rel` (7), `IntP` (6), `Coordination`, `VP` |
| `Flat` | `N`, `D` |
| `Particle` | `PP` (9) — the particle is always PP-headed in this corpus |
| `DisplacedSubj` | `NP` (10) |
| `ExtraposedSubj` | `Clause` (7) |
| `Compounding` | `VP` (3), `PP` (1) |
| `Comp_ind` | `Clause` (5), `PP` (4) |

## 5. The word tier

Word-level categories are **leaves**: `N`, `V`, `V_aux`, `P`, `D`, `Adj`,
`Adv`, `N_pro`, `Coordinator`, `Sdr`, `Int` never dominate daughters in this
corpus, with exactly two exceptions, both *containers* not phrases:
`N` with `:Flat (N …)` children (proper names: "Kofi **Annan**") and `D`
with `:Flat (D …)` (number+unit: "10 m"). Word classes also have near-dedicated
functions: `Coordinator` appears only as `:Marker` or as a `:Coordinate`
conjunct (or `Marker-Head`); `Sdr` only as `:Marker`; `Int` only as head of
`IntP` or a `Supplement`; `D` only as head of `DP`/`Det`-positions.

## 6. Linearisation (surface order)

Tree children are written in surface order, so the X-bar skeleton also
delivers the linear order of each phrase (most-frequent patterns):

```
Clause:   (Prenucleus) (Marker) (Subj) Head(V P) (Obj/Comp/PredComp…) (Mod) (Supplement) (Postnucleus)
Clause_rel: (Marker) (Prenucleus) (Subj) Head(VP) …
VP:       (Marker "to"/coordinator) (Mod) Head(V|V_aux|VP) (Obj_ind Obj_dir | Obj | Comp | PredComp |
          DisplacedSubj | ExtraposedSubj | Particle) (Mod) (Postnucleus)
NP:       (Marker) (Det|Det-Head) (Mod) Head(Nom) (Mod|Comp|Supplement|Clause_rel)
Nom:      (Det-Head) (Mod) Head(N|N_pro) (Comp) (Mod)      # pre-head Mod: AdjP/Nom; post-head: PP/Clause_rel
PP:       (Mod) Head(P) (Obj|Comp) (Mod)
AdjP:     (Mod: AdvP/DP) (Marker) Head(Adj) (Comp) (Mod)
AdvP:     (Mod) Head(Adv) (Mod)
```

Note the asymmetry licensed by the two conventions: modifiers are pre-head in
`Nom`/`AdjP`/`AdvP` but post-head in `VP`/`Clause`/`PP`/`NP`; complements are
post-head everywhere.

## 7. Empirics

`python3 cgel_conventions.py` checks all 3 conventions (projection, head
rule, function-parent licensing) mechanically:

```
total: 220 sentences, 4 exceptions
   xbar 4
```

The 4 items are deliberate, note-flagged analyses that stretch the skeleton:

* `AdjP :Mod (NP …)` for combining-form **-like** ("EPM-like", annotator
  note: p. 1711);
* `Nom :Mod (AdvP …)` for a medial adverb inside a nominal ("the arrival
  **recently**", note cites Payne/Huddleston/Pullum 2010);
* `Nom :Comp (PP_strand …)` for a stranded-preposition complement inside a
  nominal ("a book **about** ___").

Everything else — all 5566 `Head` edges, all 374 `Det` edges, every
`Subj`/`Prenucleus`/`Marker`/… — conforms.

## 8. Caveats

* The tables are empirically **complete for this corpus** but the *conventions*
  presumably admit more than the data shows (e.g. other fused categories, other
  `Marker` types); treat the counts as lower bounds on the grammar.
* `GAP` children are exempt from most constraints by design: a gap inherits the
  edge of the position it vacates, and its category is whatever the binder
  requires.
* A small number of further one-offs (e.g. `Marker → DP` for correlative
  "both") are real annotations, not parser noise; `--verbose` lists them.
