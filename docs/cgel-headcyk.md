# Head-driven (Eisner/Collins-style) CYK parser

`cgel_headcyk.py` is the recommended CGEL parser, replacing the MLE-PCFG
baseline in `cgel_cyk.py`.  Instead of reading k-ary productions off the trees
and weighting them by counts (which the tiny 220-tree corpus cannot support),
it parses with the **generative story we already fit** in
`cgel_splithead.py`: every constituent is built **outward from its head**:

    P(phrase C | head word of category L)
        = prize P(C | L)           # head rule / X-bar: the head projects
        * stop_L(C) * prod left-args  emit_L(argcat | C)
        * stop_R(C) * prod right-args emit_R(argcat | C)

Emissions are the split-head `p_dep` tables aggregated over grammatical
functions, so every side is properly normalised (`stop + sum emit = 1`) — no
partition function, no depth bound, no supercritical branching (this is the
same resolution as in `cgel-splithead.md`).

Parsing is the **Eisner-style head-outward dynamic program** over spans:

    left[i][h]  head at h, left  args over [i,h)   (base: proj + stop_L)
    right[h][k] head at h, right args over [h+1,k) (base: stop_R)
    arg[i][k]   complete constituent = max_h left[i][h] + right[h][k]

A single loop over increasing footprint keeps every dependency already
computed.  Because each constituent's head is *one* boundary token and its
arguments are complete constituents, **every surface token is used exactly
once as a head** — there is no "two heads in one constituent" divergence, and
reconstructed parses never drop or duplicate a token (verified: 130/130
parsed trees have leaf count == token count).  Unary projection chains are
folded into the single `P(C | L)` (a documented simplification: intermediate
unary nodes are absent from the produced tree).

No tuning: one smoothing constant (alpha=1.0) on the split-head tables, no
beam, no markovization.

## Results (220 sentences)

```
                     parsed   labelled F1   exact   root-match
MLE PCFG (baseline)   218/220    0.12        0       1/218
head-driven self-fit  130/220    0.30        0       —
head-driven 5-fold CV 120/220    0.31        0       2/120
```

The head-driven model more than doubles bracketing F1 (0.30 vs 0.12) with
*less* machinery.  Its coverage is lower (≈59%) and honest: it requires every
token to be the head of a phrase, so coordinations, markers (Sdr), and
GAP/displacement structures — where the head rule does not give every token a
head — are not parsed.  That is a real limitation of a pure head-driven
grammar on this corpus, reported rather than papered over.

Example — "help me prepare lunch" (`V N_pro V N`):

```
(VP (V help) (Clause (NP (N_pro me)) (V prepare)) (NP (N lunch)))
```

Run:  `python3 cgel_headcyk.py --eval`  ·  `python3 cgel_headcyk.py --demo`
Tests: `tests/cgel_headcyk.test.py`.
