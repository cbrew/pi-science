"""Zipf exponent for German verb lemmas in the first 1000 nonempty Wikipedia docs
of coral-nlp/german-commons (config web, split wikipedia)."""
import json
import time
from collections import Counter

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datasets import load_dataset
import spacy

DATASET_ID = "coral-nlp/german-commons (config=web, split=wikipedia)"
MODEL = spacy.__version__
MODEL_PKG = "de_core_news_lg"
N_DOCS = 1000

t0 = time.time()
nlp = spacy.load("de_core_news_lg", disable=["parser", "ner"])

# strided sampling
ds = load_dataset("coral-nlp/german-commons", name="web", split="wikipedia", streaming=True)
it = iter(ds)

counts = Counter()
n_docs = 0
n_tokens_processed = 0

docs = []
for row in it:
    text = row.get("text") or ""
    if not text.strip():
        continue
    docs.append(text)
    if len(docs) == N_DOCS:
        break

n_docs = len(docs)
print(f"collected {n_docs} nonempty docs in {time.time()-t0:.0f}s", flush=True)

for doc in nlp.pipe(docs, batch_size=16):
    n_tokens_processed += len(doc)
    for tok in doc:
        if tok.pos_ == "VERB":
            counts[tok.lemma_] += 1

t_proc = time.time() - t0
n_tokens = n_tokens_processed
n_lemmas = len(counts)
print(f"processed {n_tokens} tokens, {n_lemmas} distinct VERB lemmas in {t_proc:.0f}s", flush=True)

ranks = np.arange(1, len(counts) + 1)
freqs = np.array([c for _, c in counts.most_common()], dtype=float)

def fit(n):
    r = ranks[:n]
    f = freqs[:n]
    X = np.vstack([np.log(r), np.ones_like(r, dtype=float)]).T
    y = np.log(f)
    beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    slope = beta[0]            # log(freq) = slope*log(rank) + intercept
    intercept = beta[1]
    pred = X @ beta
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot
    # std error of slope
    n0 = len(r)
    dof = n0 - 2
    sigma2 = ss_res / dof
    se = float(np.sqrt(sigma2 / np.sum((np.log(r) - np.log(r).mean()) ** 2)))
    return slope, intercept, r2, se

results = {}
for n in (100, 500, 1000):
    if n_lemmas < n:
        fitted = fit(n_lemmas)
        results[str(n)] = {
            "available": False, "n_available": int(n_lemmas),
            "slope": fitted[0], "intercept": fitted[1], "r2": fitted[2], "se": fitted[3],
        }
    else:
        fitted = fit(n)
        results[str(n)] = {
            "available": True, "n_available": int(n),
            "slope": fitted[0], "intercept": fitted[1], "r2": fitted[2], "se": fitted[3],
        }

# ---- plot ----
fig, ax = plt.subplots(figsize=(8, 6))
ax.loglog(ranks, freqs, ".", markersize=3, alpha=0.6, color="tab:blue", label="observed verb lemmas")
rr = np.logspace(0, np.log10(len(ranks)), 400)
for n in (100, 500, 1000):
    if n_lemmas < n:
        continue
    s = results[str(n)]["slope"]; b = results[str(n)]["intercept"]
    ax.loglog(rr[:n], np.exp(b) * rr[:n] ** s, "-", lw=2,
              label=f"ranks 1\u2013{n}: \u03b2={abs(s):.3f}")
ax.set_xlabel("rank")
ax.set_ylabel("frequency")
ax.set_title(f"Zipf plot: German verb lemmas ({n_lemmas} lemmas, {n_tokens} tokens)")
ax.legend()
fig.tight_layout()
fig.savefig("zipf_plot.png", dpi=150)

out = {
    "dataset_id": DATASET_ID,
    "spacy_version": MODEL,
    "spacy_model": MODEL_PKG,
    "n_docs": n_docs,
    "n_tokens_verb_and_other": int(n_tokens),
    "n_distinct_verb_lemmas": int(n_lemmas),
    "results": results,
    "fit_method": "OLS of log(frequency) on log(rank); slope reported as Zipf exponent beta=-slope",
}
with open("zipf_results.json", "w") as fh:
    json.dump(out, fh, indent=2)

print(json.dumps(out, indent=2))
print("plotted -> zipf_plot.png")