"""Model B over the chart: a conditional log-linear model, fitted.

``cgel_coordgap.py`` scores an analysis by a product of relative-frequency
tables under hard constraints (the gap discipline, like-category
coordination, the marker schema).  As ``docs/cgel-models.md`` says of its
Model B, the right way to use such tables with constraints is as a
log-linear model whose normaliser runs *only over the analyses the
constraints admit*, with the weights fitted to that normaliser rather than
read off counts.  This module does that for the chart:

    P(analysis | string) = exp( sum of feature weights ) / Z(string)
    Z(string)            = sum over all chart analyses of the string

* ``inside``  — the chart in the sum semiring: ``log Z``;
* ``outside`` — the outside pass over the recorded edges: expected feature
  counts ``E[f | string]`` under the model, exactly;
* ``gold_features`` — the feature counts of the treebank analysis, read
  off the same extraction the tables came from;
* ``fit`` — conditional maximum likelihood by gradient ascent on
  ``sum_s [ f(gold_s) - E[f | string_s] ]`` with an L2 penalty, from the
  relative-frequency initialisation.

The features are the local events of the chart (``feature_weights`` in
``cgel_coordgap``).  The model is conditional on the token string, gap
positions included, exactly as the parser is.  Overlapping features (a
node's category appears in its parent's ``dep`` feature and in its own
``proj`` feature) are no longer a double count: the weights are fitted
jointly against one normaliser.

Sentences whose treebank analysis lies outside the chart's support (an
unfoldable node, an unseen marker, the two unparsed sentences) have no
defined conditional likelihood and are left out of training; they are
counted and reported.

Run:    python3 cgel_coordgap_fit.py --check        (gradient check)
        python3 cgel_coordgap_fit.py --fit --maxtok 16 --epochs 20
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cgel_reader import Sentence, parse_cgel_file
import cgel_coordgap as P
from cgel_coordgap import (Chart, Grammar, LOG0, _logaddexp, build_grammar,
                           iter_events, sentence_tokens, sentence_words)

CGEL = Path(__file__).resolve().parent / "cgel"


# ---------------------------------------------------------------------------
# inside / outside
# ---------------------------------------------------------------------------

def inside(g: Grammar, s: Sentence, maxgap: int = P.MAXGAP, record: bool = False
           ) -> Chart:
    return Chart(g, sentence_tokens(s), sentence_words(s), maxgap,
                 mode="sum", record=record).run()


def outside(chart: Chart) -> Tuple[float, Dict[tuple, float]]:
    """Expected feature counts under the model, from a recorded sum-mode
    chart.  Returns ``(log Z, {feature: E[count]})``.

    Outside masses are propagated over the recorded edges in reverse
    creation order, which is reverse topological order: every edge was
    recorded after all the edges that build its tails."""
    logZ = chart.log_inside()
    if logZ == LOG0:
        return logZ, {}
    out: Dict[Tuple[int, tuple], float] = {}
    for cell, key, _ in chart.roots:
        out[(id(cell), key)] = 0.0
    expect: Dict[tuple, float] = defaultdict(float)
    w = chart.w
    for cell, key, tails, feats in reversed(chart.edges):
        o = out.get((id(cell), key))
        if o is None:
            continue
        ew = sum(w[f] for f in feats)
        ins = [tcell[tkey][0] for tcell, tkey in tails]
        total = o + ew + sum(ins)                 # mass through this edge
        m = math.exp(total - logZ)
        for f in feats:
            expect[f] += m
        for j, (tcell, tkey) in enumerate(tails):
            contrib = total - ins[j]
            k = (id(tcell), tkey)
            out[k] = contrib if k not in out else _logaddexp(out[k], contrib)
    return logZ, dict(expect)


# ---------------------------------------------------------------------------
# the gold analysis as features
# ---------------------------------------------------------------------------

def gold_features(s: Sentence, g: Grammar) -> Optional[Counter]:
    """Feature counts of the treebank analysis in the chart's terms, or
    ``None`` if it is not in the chart's support (an unfoldable node, or a
    feature the grammar does not have)."""
    c: Counter = Counter()
    for ev in iter_events(s, g.markers):
        if ev[0] == "proj":
            _, C, L, left, right, _chain, _lv = ev
            c[("proj", L, C)] += 1
            fr = ("frame", C, P.frame_of(f for f, _ in left + right))
            c[fr if fr in g.w else ("frame-unseen", C)] += 1
            for side, seq in (("L", left), ("R", right)):
                c[("stop", C, side)] += 1
                for f, D in seq:
                    c[("dep", C, side, f, D)] += 1
        elif ev[0] == "leaf":
            c[("leaf", ev[1])] += 1
        elif ev[0] == "mark":
            _, kind, word, X, _isconj = ev
            if g.markers == "dependent":
                if kind == "Coordinator":
                    c[("conj", "marked")] += 1
                continue
            f = ("mark", kind, word, X)
            if f not in g.w:
                f = ("markk", kind, X)
            c[f] += 1
            if kind == "Coordinator":
                c[("conj", "marked")] += 1
        elif ev[0] == "coord":
            _, X, n, bare, ok = ev
            if not ok:
                return None
            c[("coord", "last")] += 1
            c[("coord", "more")] += n - 2
            c[("conj", "bare")] += bare
        else:
            return None
    for f in c:
        if f not in g.w:
            return None
    return c


def gold_score(c: Counter, g: Grammar) -> float:
    return sum(v * g.w[f] for f, v in c.items())


def loglik(g: Grammar, s: Sentence, maxgap: int = P.MAXGAP) -> Optional[float]:
    """log P(gold analysis | string), or None if the gold is off-support."""
    c = gold_features(s, g)
    if c is None:
        return None
    logZ = inside(g, s, maxgap).log_inside()
    if logZ == LOG0 or gold_score(c, g) > logZ + 1e-6:
        return None                        # not an analysis of the chart
    return gold_score(c, g) - logZ


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def gradient_check(g: Grammar, s: Sentence, nfeat: int = 6, eps: float = 1e-4
                   ) -> List[Tuple[tuple, float, float]]:
    """Compare E[f] from the outside pass with the finite-difference
    derivative of log Z with respect to the feature's weight."""
    ch = inside(g, s, record=True)
    logZ, ex = outside(ch)
    rows = []
    rng = random.Random(0)
    feats = sorted(ex, key=lambda f: -ex[f])
    for f in feats[:nfeat // 2] + rng.sample(feats, min(nfeat - nfeat // 2, len(feats))):
        w0 = g.w[f]
        g.w[f] = w0 + eps
        zp = inside(g, s).log_inside()
        g.w[f] = w0 - eps
        zm = inside(g, s).log_inside()
        g.w[f] = w0
        rows.append((f, ex[f], (zp - zm) / (2 * eps)))
    return rows


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

def fit(g: Grammar, train: Sequence[Sentence], epochs: int = 10, lr: float = 0.05,
        l2: float = 0.1, maxgap: int = P.MAXGAP, verbose: bool = True
        ) -> Dict[str, list]:
    """Conditional maximum likelihood with an L2 penalty towards the
    relative-frequency initialisation, by Adam.  Modifies ``g.w`` in place
    and returns the per-epoch mean log-likelihood."""
    golds = []
    skipped = unexplained = 0
    for s in train:
        c = gold_features(s, g)
        if c is None:
            skipped += 1
            continue
        logZ = inside(g, s, maxgap).log_inside()
        if logZ == LOG0 or gold_score(c, g) > logZ + 1e-6:
            unexplained += 1               # gold above Z: not in the support
            continue
        golds.append((s, c))
    w0 = dict(g.w)
    m: Dict[tuple, float] = defaultdict(float)
    v: Dict[tuple, float] = defaultdict(float)
    b1, b2, epsa = 0.9, 0.999, 1e-8
    hist = {"loglik": [], "skipped": skipped, "unexplained": unexplained,
            "n": len(golds)}
    t = 0
    for ep in range(1, epochs + 1):
        grad: Dict[tuple, float] = defaultdict(float)
        ll = 0.0
        for s, c in golds:
            ch = inside(g, s, maxgap, record=True)
            logZ, ex = outside(ch)
            if logZ == LOG0:
                continue
            ll += gold_score(c, g) - logZ
            for f, n in c.items():
                grad[f] += n
            for f, e in ex.items():
                grad[f] -= e
        for f in grad:
            grad[f] -= l2 * (g.w[f] - w0[f])
        t += 1
        for f, gr in grad.items():
            m[f] = b1 * m[f] + (1 - b1) * gr
            v[f] = b2 * v[f] + (1 - b2) * gr * gr
            mh = m[f] / (1 - b1 ** t)
            vh = v[f] / (1 - b2 ** t)
            g.w[f] += lr * mh / (math.sqrt(vh) + epsa)
        hist["loglik"].append(ll / max(1, len(golds)))
        if verbose:
            print(f"  epoch {ep:3d}  mean log P(gold | string) = {ll / max(1, len(golds)):.3f}",
                  flush=True)
    return hist


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="gradient check")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--maxtok", type=int, default=16,
                    help="train on sentences of at most this many tokens")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--l2", type=float, default=0.1)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()
    sentences = [s for f in sorted(CGEL.glob("*.cgel")) for s in parse_cgel_file(str(f))]
    if args.check:
        g = build_grammar(sentences)
        for sub in ("help me prepare lunch", "would this -- be fine",
                    "fire alarm and strobe light"):
            s = next(s for s in sentences if sub in s.sent)
            print(f"\n{s.sent}")
            ll = loglik(g, s)
            print(f"  log P(gold | string) = {ll:.3f}" if ll is not None
                  else "  gold off-support")
            for f, e, fd in gradient_check(g, s):
                print(f"  {str(f):55s} E[f]={e:.5f}  dlogZ/dw={fd:.5f}  "
                      f"{'ok' if abs(e - fd) < 1e-3 else 'MISMATCH'}")
    if args.fit:
        rng = random.Random(0)
        order = list(sentences)
        rng.shuffle(order)
        size = (len(order) + args.folds - 1) // args.folds
        rows_before, rows_after = [], []
        for fold in range(args.folds):
            test = order[fold * size:(fold + 1) * size]
            train = [s for s in order if s not in test]
            g = build_grammar(train)
            rows_before += P.evaluate(test, g)
            short = [s for s in train if len(sentence_tokens(s)) <= args.maxtok]
            print(f"fold {fold}: fitting on {len(short)} sentences <= {args.maxtok} tokens")
            h = fit(g, short, args.epochs, args.lr, args.l2)
            print(f"  off-support: {h['skipped']} by extraction, "
                  f"{h['unexplained']} by the support check; trained on {h['n']}")
            rows_after += P.evaluate(test, g)
        print(P.summarize(rows_before, f"{args.folds}-fold CV, relative-frequency weights"))
        print(P.summarize(rows_after, f"{args.folds}-fold CV, fitted (Model B over the chart)"))


if __name__ == "__main__":
    main()
