# Correction plan: reader–parser interface and X-bar in the parser

This is a plan, not a record of work done.  It follows a review that found
two kinds of fault in `cgel_coordgap.py`: the parser discards most of what
the reader provides, and it folds the treebank's projection levels into
one item per head and then guesses them back.  Both are symbolic errors;
nothing in this plan concerns probabilities.  Each step is small, has a
check that can be read in a minute, and can be reverted on its own.

## Part A: the reader–parser interface

**A1. One canonical token sequence.**  The reader offers three views of the
string (`tokens()` without gaps, `surface_events()` with gaps, and the
parser's own `sentence_tokens`).  Replace them, for everything downstream,
by one function on a `Sentence` that yields, in `# sent` order, one record
per surface position: the node, its word class, surface form, lemma,
`xpos`, attached punctuation, and whether it is a gap.  Extraction, the
parser input and the evaluation all read this and nothing else.
*Check*: joining the records reproduces `# sent` for all 220 sentences
(the reader's validator already does this for its own view).

**A2. Word classes refined from the annotation, at load time.**  The parser
takes the treebank's word classes as input; the treebank carries finer
distinctions that it does not spell out as classes.  Make them classes,
in one load-time function, documented as data interventions:

* verbs and auxiliaries by finiteness from `xpos`, which every one of the
  716 carries: finite (`VBZ`, `VBD`, `VBP`), non-finite (`VB`, `VBG`,
  `VBN`), modal (`MD`);
* complement-taking nouns and adjectives (`N_c`, `Adj_c`), already done;
* the eight complement-taking determinatives (`D_c`), optionally.

*Check*: the per-class argument table (which classes take `Subj`, `Obj`,
`Comp`, `Det`) shows finiteness separating subject-taking from
non-subject-taking verbs, and no class outside the intended ones taking
complements.

**A3. Carry lemma and punctuation.**  The parser input gains the lemma
(for any later lexicalised decision) and a punctuation flag per token
(for coordination and supplement boundaries).  Carried, not yet used.
*Check*: none needed beyond A1.

**A4. The three token-less leaves.**  Three annotator-supplied words
(`:correct` without `:t`) are neither tokens nor gaps.  Decide once: treat
their phrases as unfoldable (current behaviour, three sentences
affected) and say so in the data note.

## Part B: X-bar in the parser (revised after reading the CGELBank policy)

**B0. The finding, corrected.**  The projection layers are not a statistical
regularity to be learned but a stated annotation policy of CGELBank, quoted
in Brew's *CGEL phenomena* notes: dependents attach one at a time going
outward from the head, forming intermediate layers; a verb's internal
complements share the layer over the word; in a nominal every complement and
modifier has its own Nom layer and the determiner is external; unary
branches are always shown; post-head modifiers attach as low as possible; a
modifier between a head and its complement takes the inner layer.  The
auxiliary heads a VP whose complement is a clause, so the subject attaches
at the clause of the finite verb or auxiliary.

**B1. Verified.**  `cgel_layering.py` writes that policy as a function from
(head class, ordered dependents with functions, the category the context
requires at the top) to the chain of layers.  Against the gold trees it
reproduces the chain exactly for 2,996 of 3,094 heads (96.8%).  The 98
residual heads are annotator choices no policy settles: an end-position
adjunct attached at the clause rather than the VP, an external modifier on
the NP rather than inside the nominal, a fused determiner-head modified on
the DP, a nominal with its complement outside its modifiers.

**B2. Consequence.**  No level chart.  The parser's object is the headed
dependency structure with function labels; the X-bar tree is a
deterministic rendering of it by `cgel_layering.layer`, and the four
residual choices are the only layer decisions a parser has to make.  What
folding erased is restored not by parsing levels but by carrying, in the
chart, the constraints the layers encode:

* the subject is licensed once, and only by a finite head (finiteness from
  `xpos`, Part A2), because `Subj` attaches at `Clause` over the finite
  verb's `VP` and nowhere else;
* the determiner is licensed once, at `NP` over `Nom`;
* a head's complements are licensed by its class at the layer over the
  word, which is where valency lives and where `N_c`/`Adj_c` act;
* modifiers are not limited, one per layer;
* a coordination's conjuncts fill one function slot (CGEL's condition is
  likeness of function; CGELBank reads the coordination's nature off the
  conjuncts' categories; to be settled with the author, step 4 of the
  working list);
* gaps keep their category-carrying discharge, with the constructions
  (subject–auxiliary inversion, subject–dependent inversion, delayed right
  constituent coordination, relativisation, preposing, postposing)
  naming which binder goes with which gap.

**B3. Dropped.**  The valency frame feature, the attested-frame bound and
the level chart of the earlier draft.

## Order of work and the check at each step

| step | change | check |
|---|---|---|
| 1 | A1 canonical sequence | `# sent` round trip, 220/220 |
| 2 | A2 finiteness classes | per-class argument table |
| 3 | A3 lemma and punctuation carried | none |
| 4 | B1 layering function | gold chain reproduced for ≥ 95% of heads; residue listed (done: 96.8%) |
| 5 | B2 constraints in the chart, one at a time, frame feature off | repeated-argument count and LAS on sentences ≤ 14 tokens after each |
| 6 | coordination condition, after settling CGEL against CGELBank | the nine unlike-category cases |
| 7 | Model B fit on the corrected chart | held-out LAS and gap filling, with the support test |

Steps 1–4 touch no parsing rule; step 4 is done and is what makes step 5
well defined.
