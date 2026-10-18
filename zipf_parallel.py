"""Collect German VERB-lemma statistics over the coral-nlp/german-commons wikipedia split,
parallelized across worker processes (default 6).

Parent process: streams documents lazily from HF, feeds fixed-size text chunks to workers.
Workers: count tokens tagged VERB (AUX excluded), lemmatized with de_core_news_lg
(parser/NER disabled). Counters are aggregated in the parent.

On Linux/macOS with the 'fork' start method workers inherit the loaded spaCy model from
the parent (copy-on-write), so the model is loaded once and RAM stays low.
If fork is unavailable, each worker loads the model itself.

Usage:
    python zipf_parallel.py                  # entire wikipedia split, 6 workers
    python zipf_parallel.py --docs 100000    # first 100k nonempty docs
    python zipf_parallel.py --workers 6 --chunk 64 --out zipf_full_counts.json
"""
import argparse
import json
import multiprocessing as mp
import time
from collections import Counter

import numpy as np

MODEL = "de_core_news_lg"
DATASET_ID = "coral-nlp/german-commons (config=web, split=wikipedia)"

nlp = None  # in fork mode: inherited by workers from the parent


def _load_model():
    import spacy
    return spacy.load(MODEL, disable=["parser", "ner"])


def _worker_init():
    global nlp
    nlp = _load_model()  # only used with spawn start method


def _process_chunk(texts):
    """Count VERB lemmas in one chunk of documents. Returns (n_tokens, n_docs, Counter)."""
    c = Counter()
    n_tok = 0
    for doc in nlp.pipe(texts, batch_size=32):
        n_tok += len(doc)
        for tok in doc:
            if tok.pos_ == "VERB":
                c[tok.lemma_] += 1
    return n_tok, len(texts), c


def _make_pool(workers):
    try:
        ctx = mp.get_context("fork")
        return ctx.Pool(workers)
    except (ValueError, AttributeError):  # fork unavailable -> spawn with per-worker load
        return mp.Pool(workers, initializer=_worker_init)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--docs", type=int, default=0, help="limit to first N nonempty docs; 0 = entire split")
    ap.add_argument("--chunk", type=int, default=64, help="docs per worker task")
    ap.add_argument("--out", default="zipf_verb_counts.json", help="output JSON with counts + fits")
    ap.add_argument("--no-plot", action="store_true", help="skip the rank-frequency plot")
    args = ap.parse_args()

    t0 = time.time()
    global nlp
    nlp = _load_model()  # loaded in parent; children inherit it via fork
    print(f"model loaded ({time.time()-t0:.0f}s)", flush=True)

    from datasets import load_dataset

    ds = load_dataset("coral-nlp/german-commons", name="web", split="wikipedia", streaming=True)

    def doc_gen():
        buf = []
        n = 0
        for row in ds:
            t = (row.get("text") or "").strip()
            if not t:
                continue
            buf.append(t)
            if len(buf) == args.chunk:
                yield buf
                buf = []
            n += 1
            if args.docs and n >= args.docs:
                break
        if buf:
            yield buf

    pool = _make_pool(args.workers)
    total = Counter()
    n_tok = n_docs = 0
    started = time.time()
    try:
        for i, (nt, nd, c) in enumerate(pool.imap_unordered(_process_chunk, doc_gen(), chunksize=1)):
            total.update(c)
            n_tok += nt
            n_docs += nd
            if (i + 1) % 100 == 0:
                rate = n_tok / (time.time() - started)
                print(f"{n_docs} docs | {n_tok} tokens | {rate:.0f} tok/s | {time.time()-started:.0f}s", flush=True)
    except KeyboardInterrupt:
        print("interrupted; terminating workers", flush=True)
        pool.terminate()
        raise
    finally:
        pool.close()
        pool.join()

    elapsed = time.time() - started
    print(f"done: {n_docs} docs, {n_tok} tokens, {len(total)} distinct VERB lemmas in {elapsed:.0f}s "
          f"({n_tok/elapsed:.0f} tok/s)", flush=True)

    ranks = np.arange(1, len(total) + 1)
    freqs = np.array([total[l] for l, _ in total.most_common()], dtype=float)

    def fit(n):
        r, f = ranks[:n], freqs[:n]
        X = np.vstack([np.log(r), np.ones_like(r, dtype=float)]).T
        y = np.log(f)
        beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ beta
        r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
        se = float(np.sqrt(np.sum((y - pred) ** 2) / (len(r) - 2)
                           / np.sum((np.log(r) - np.log(r).mean()) ** 2)))
        return float(beta[0]), float(beta[1]), float(r2), se

    results = {}
    for win in (100, 500, 1000):
        if len(total) < win:
            s, b, r2, se = fit(len(total))
            results[str(win)] = {"n_available": len(total), "slope": s, "intercept": b, "r2": r2, "se": se}
        else:
            s, b, r2, se = fit(win)
            results[str(win)] = {"n_available": win, "slope": s, "intercept": b, "r2": r2, "se": se}

    out = {
        "dataset_id": DATASET_ID,
        "spacy_model": MODEL,
        "n_workers": args.workers,
        "n_docs": n_docs,
        "n_tokens": int(n_tok),
        "n_distinct_verb_lemmas": len(total),
        "elapsed_s": round(elapsed, 1),
        "fit_method": "OLS of log(freq) on log(rank); Zipf exponent beta=-slope",
        "results": results,
        "counts": dict(total.most_common()),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {args.out}", flush=True)

    if not args.no_plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.loglog(ranks, freqs, ".", markersize=3, alpha=0.6, color="tab:blue",
                  label=f"observed verb lemmas ({len(total)})")
        rr = np.logspace(0, np.log10(max(len(ranks), 1)), 400)
        for win in (100, 500, 1000):
            if len(total) < win:
                continue
            r2 = results[str(win)]["r2"]
            s, b = results[str(win)]["slope"], results[str(win)]["intercept"]
            ax.loglog(rr[:win], np.exp(b) * rr[:win] ** s, "-", lw=2,
                      label=f"ranks 1\u2013{win}: \u03b2={abs(s):.3f} (R\u00b2={r2:.2f})")
        ax.set_xlabel("rank")
        ax.set_ylabel("frequency")
        ax.set_title(f"Zipf plot: German VERB lemmas, {n_docs:,} Wikipedia docs")
        ax.legend()
        fig.tight_layout()
        fig.savefig("zipf_parallel_plot.png", dpi=150)
        print("wrote zipf_parallel_plot.png", flush=True)


if __name__ == "__main__":
    main()