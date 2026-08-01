# Scoring Bake-off Results — 2026-08-01

Human-readable companion to `data/processed/scoring_bakeoff_report.csv` (the raw numbers) and
`data/provenance.jsonl` (the audit trail). Every figure below is explained in place — see
`STEPS_Progress.md`'s Step 11 for the general "how each algorithm works" / "what does AUROC mean"
background; this file is the specific results from the run you did in your own terminal.

## Run details

- **Command:** `docker compose run --rm pipeline dome-triage keywords scoring-bakeoff`
- **When:** 2026-08-01T07:20:13Z UTC (finish time). **Duration: 753.8s (~12.6 minutes)** for all
  6 rows (3 scorers × 2 conditions).
- **Inputs:** `keyword_lexicon.csv` (296 positive terms), `keyword_lexicon_exclusionary.csv`
  (18 negative/exclusionary terms) — both from Step 8d's tier-3 promotion — and
  `canonical_dataset.csv` (4,320 total records, verified by direct parse).

## How many positive and negative papers were actually presented to the algorithms

This is the same set for every scorer and both conditions — apples-to-apples throughout:

| | Count | % of canonical dataset |
|---|---|---|
| **Positive** (`label == "positive"`) | **1,878** | 43.5% |
| **Negative** (`label == "negative"`) | **1,907** | 44.1% |
| **Total evaluated** | **3,785** | 87.6% |
| *(excluded: `skipped`)* | *533* | *12.3%* |
| *(excluded: `conflict`)* | *2* | *0.05%* |
| *(canonical dataset total)* | *4,320* | *100%* |

`skipped`/`conflict`-labeled records are excluded because they're not a definitive positive/
negative ground truth — including them would inject label noise into the evaluation. Positive and
negative are almost perfectly balanced (43.5% / 44.1%), so accuracy is a meaningful number here,
not misleading the way it can be on a heavily imbalanced dataset.

## Full results

All figures directly from `scoring_bakeoff_report.csv`, rounded to 4 significant figures for
readability (the CSV has full precision). Explanation of every column further down.

### BM25

| Condition | AUROC | Threshold | Accuracy | Precision | Recall | F1 | TP | TN | FP | FN |
|---|---|---|---|---|---|---|---|---|---|---|
| Positive lexicon only | 0.7669 | 107.2 | 77.23% | 83.51% | 67.41% | 0.7460 | 1266 | 1657 | 250 | 612 |
| + Exclusionary lexicon | **0.7737** | 107.6 | 77.23% | **84.19%** | 66.61% | 0.7438 | 1251 | 1672 | 235 | 627 |

**What happened:** adding the exclusionary lexicon barely moved BM25 at all — AUROC up a
negligible +0.0068 (+0.9% relative), accuracy exactly unchanged, precision up slightly
(fewer false alarms: FP dropped 250→235), recall down slightly (a few more genuine positives
missed: FN rose 612→627). **Reading:** BM25 was already the most stable, precision-leaning scorer
of the three, and the exclusionary lexicon nudges it marginally further in that direction without
materially changing its overall discrimination ability.

### TF-IDF cosine

| Condition | AUROC | Threshold | Accuracy | Precision | Recall | F1 | TP | TN | FP | FN |
|---|---|---|---|---|---|---|---|---|---|---|
| Positive lexicon only | 0.7647 | 0.0551 | 76.06% | 76.97% | 73.86% | 0.7538 | 1387 | 1492 | 415 | 491 |
| + Exclusionary lexicon | **0.7969** | 0.0494 | **76.75%** | **78.84%** | 72.63% | **0.7561** | 1364 | 1541 | 366 | 514 |

**What happened:** this is the clearest, most meaningful improvement of the three scorers — AUROC
up +0.0322 (+4.2% relative, roughly 4-5× the size of BM25's improvement), accuracy up, precision up
(FP dropped 415→366, i.e. 49 fewer false alarms), F1 up slightly, at a small recall cost (23 more
genuine positives missed). **Reading:** TF-IDF-cosine benefits the most from the exclusionary
lexicon of the three algorithms — real, measurable evidence that the exclusionary terms you and I
curated (the `forest`/`random`/`neural`/`area`/`bayes` generic-word counterweights plus the
non-methods-pubtype terms) are doing genuine work, not just a nice idea. **This is the best single
result across all 6 rows** (highest AUROC, highest F1).

### weighted-sum

| Condition | AUROC | Threshold | Accuracy | Precision | Recall | F1 | TP | TN | FP | FN |
|---|---|---|---|---|---|---|---|---|---|---|
| Positive lexicon only | 0.7004 | 0.0323 | 72.42% | 71.43% | 74.01% | 0.7270 | 1390 | 1351 | 556 | 488 |
| + Exclusionary lexicon | ~~0.4537~~ ⚠️ | ~~0.0325~~ | ~~55.22%~~ | ~~61.60%~~ | ~~25.88%~~ | ~~0.3645~~ | ~~486~~ | ~~1604~~ | ~~303~~ | ~~1392~~ |

**⚠️ The exclusionary-lexicon row above is from a run affected by a real bug, now fixed in code
(commit after this run) — re-run to get corrected numbers before trusting them.** What happened:
`WeightedSumScorer`'s exclusionary penalty was subtracting an *unweighted count* (1.0 per matched
exclusionary term) instead of that term's own small weight. Real `discriminative_score` values are
tiny (~0.0001–0.02), so a *single* exclusionary match (very likely, since several exclusionary
terms are common generic words like "forest"/"random"/"neural") swamped an entire paper's positive
sum by roughly 50–100×, driving AUROC **below 0.5 — worse than random guessing** — and collapsing
recall from 74% to 26% (most genuine positives, including real `random forest`/`neural network`
papers that also happen to contain the bare words "random"/"forest"/"neural", got pushed to a
strongly negative score and misclassified). Fixed: the scorer now uses each exclusionary term's
own weight (absolute value, so a term manually reclassified from the positive pile — which keeps
its original positive-signed `discriminative_score` — still correctly subtracts rather than
flipping sign and rewarding a match). BM25 and TF-IDF-cosine were never affected by this, since
their exclusionary penalty is computed via the same scoring mechanism as the positive score on
both sides (same units), not a separate raw count.

## Metrics glossary

| Metric | Meaning |
|---|---|
| **AUROC** | Area under the ROC curve — how well the scorer ranks positives above negatives across *all* possible thresholds. 0.5 = no better than random guessing, 1.0 = perfect ranking, **below 0.5 = actively worse than random** (systematically backwards). |
| **Threshold** | The specific score value above which a paper is called "positive" for every metric to its right. Chosen as each scorer's Youden's-J-optimal point (maximizes true-positive-rate minus false-positive-rate on its own ROC curve) — a standard, principled operating point, not an arbitrary guess. |
| **Accuracy** | Of all 3,785 papers, what fraction were classified correctly (either genuinely positive and flagged positive, or genuinely negative and flagged negative). |
| **Precision** | Of the papers the scorer *flagged* as positive, what fraction were *actually* positive. High precision = few false alarms. |
| **Recall** | Of the papers that were *actually* positive, what fraction the scorer correctly flagged. High recall = few genuine positives missed. |
| **F1** | Harmonic mean of precision and recall — one balanced number. |
| **TP** (True Positive) | Genuinely positive papers correctly flagged positive. |
| **TN** (True Negative) | Genuinely negative papers correctly flagged negative. |
| **FP** (False Positive) | Genuinely negative papers *wrongly* flagged positive — a false alarm. |
| **FN** (False Negative) | Genuinely positive papers *wrongly* flagged negative — a miss. |

## My feedback / recommendation

**Overall: the bake-off worked, and it did its actual job — it found a real bug, not just ranked three working algorithms.** That's the system functioning as designed (`ROADMAP.md`: "validate every relevance-scoring algorithm... before trusting any of them"), not a failure.

1. **Best result: TF-IDF-cosine + exclusionary lexicon** (AUROC 0.797, F1 0.756). It benefited from the exclusionary lexicon by far the most of the three, and by a large enough margin (4-5× BM25's improvement) that I don't think it's noise — though to say that with statistical rigor would need a bootstrap confidence interval or DeLong's test, which isn't built yet (that's explicitly a later-phase item in `ROADMAP.md`'s Model Evaluation Standards, not something Phase 1's bake-off does). Treat "clearly the biggest mover of the three" as suggestive, not proven, until that exists.
2. **Close, very stable second: BM25** (AUROC 0.767→0.774, barely moves either way, consistently the highest precision of the three). If you'd rather have a scorer that's less sensitive to exactly which exclusionary terms you curate, BM25 is the safer, more boring choice — genuinely not a bad thing at this stage.
3. **weighted-sum**: already the weakest scorer on positive-lexicon-only grounds (AUROC 0.700 vs ~0.76-0.77 for the other two — consistent with the original 2026-07-28 finding). Its exclusionary-lexicon number is now fixed in code but **not yet re-run** — if you want the corrected comparison, re-run `keywords scoring-bakeoff` (the fix doesn't change the other two scorers' numbers, only weighted-sum's exclusionary row). Given it was already the intended fallback/baseline rather than a production candidate, I wouldn't block on re-running just for this, but I would not trust the struck-through numbers above for any real decision.

**For Step 12, I'd lean TF-IDF-cosine with the exclusionary lexicon applied** (`--scorer tfidf-cosine`, which now defaults to using `keyword_lexicon_exclusionary.csv` automatically if present, `--exclusionary-weight 1.0`) — but this is genuinely your call to make, exactly as `STEPS_Progress.md` says: don't rubber-stamp it.

## What's next

Fill in Step 11's Log block in `STEPS_Progress.md` (now points here), then move to Step 12
(`keywords score-bulk-match`) with whichever scorer you choose.
