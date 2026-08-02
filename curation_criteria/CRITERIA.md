# Curation criteria — living document

**This file is yours to edit.** It's not a spec I maintain — it's your working rulebook for the
Positive/Negative/Undeterminable/Skipped decisions you make in the Curate app
(`docker compose up curate`), meant to grow as you go. Everything below marked *Suggested* is a
starting point, not a rule — override, delete, or rewrite any of it. What matters is that
whatever you land on gets written down **here**, so it stays the same on day 40 of curation as it
was on day 1.

## Why this matters for the actual goal

The end target is a **balanced positive/negative dataset of genuine AI/ML-methods papers**, used
to fine-tune a BERT-family classifier that will then triage the rest of the ~750k Europe PMC
records that mention "artificial intelligence" or "machine learning" (and eventually wider EPMC).
A fine-tuned classifier can only be as clean as the decision boundary it's trained on. If your own
bar for "positive" quietly shifts partway through — e.g. stricter about requiring deep learning
early on, then later also accepting plain regression — the training set ends up with contradictory
examples on either side of that shift, and the model has no way to resolve the contradiction; it
just gets noisier. This file exists so that doesn't happen silently. If you find yourself wanting
to change a rule, **update this file with a dated note** (see the changelog at the bottom of each
section) rather than just deciding differently going forward — that dated note is what lets you
decide later whether earlier decisions need a second pass.

## The four categories (exact match to the Curate app's decision buttons)

---

## Positive

**Rule of thumb:** the paper *applies* an ML/AI method as a genuine part of its own methodology —
ML/AI is part of **how the study was done**, not just something it mentions.

### Include when
- The authors train, fit, apply, or evaluate a specific ML/AI model/algorithm as part of their own
  methodology, on data they analyze in the paper.
- Both "applies an existing algorithm to new data" and "proposes a new algorithm/architecture"
  count — this project doesn't distinguish those two for labeling purposes.
- ML/AI is one of several methods used (e.g. a paper primarily about traditional statistics that
  also fits a random forest as a comparison) — still positive if that component is real and
  substantive, not decorative.

### Exclude when (→ this is what makes something Negative instead)
- ML/AI is mentioned only in the introduction/background/related-work, as context, without the
  authors using it themselves.
- ML/AI appears only as a suggested future direction ("future work could apply deep learning...").

### Suggested edge-case guidance
- **Classical methods (plain linear/logistic regression, decision trees, k-means, etc.) with no
  "fancier" ML alongside them — does this count as positive?** *Suggested default: yes.* DOME's
  own scope covers supervised ML broadly, not just deep learning, and this project's keyword
  lexicon already treats `regression`/`classifier`/`svm`/`cnn`/`xgboost` etc. as protected positive
  terms (see `PREPROCESSING.md` / `keywords/curated_terms.py::PROTECTED_UNIGRAMS`) — keeping this
  consistent with the lexicon's own scope avoids training the classifier against a stricter bar
  than the data pipeline that fed it candidates in the first place.
- **A tool/software paper that packages an ML method (e.g. a bioinformatics package release) —
  positive or not?** *Suggested default: positive*, if the paper itself validates/evaluates the ML
  component on real data (not just "the package supports classifier X" with zero evaluation).
- **A protocol or methods-only paper that proposes to use ML but has no results yet.** Genuinely
  ambiguous — *suggested default: Undeterminable, not Skipped* (see below for the distinction) — you
  looked, it's a real judgment call, not something you're deferring out of time pressure.

### Your notes & examples (add as you go)
<!-- e.g. 2026-08-05, PMID 12345678: borderline case, decided positive because Y -->

---

## Negative

**Rule of thumb:** the paper does *not* apply ML/AI as genuine methodology — either it's about
something else, or ML/AI only appears in a non-methodological way.

### Include when
Each of these lines up with one of the `close_negative_reason` options already captured in the app
(`configs/curation_features.yaml`) — pick the matching reason there when you mark negative:
- Purely theoretical/mathematical proposal with no applied component or real-data evaluation →
  `theoretical-method-only`.
- Generic NLP/text-extraction work that isn't really ML methodology in the sense this project
  cares about → `generic-nlp-extraction-only`.
- Wrong domain entirely, or "AI"/"ML" used in an unrelated/non-computational sense that slipped
  through the search → `wrong-domain-non-bio`.
- A review/survey that discusses other people's ML methods without applying one itself →
  `review-mentions-ml-only`.
- Perspective, opinion, commentary, editorial, case report, letter to the editor, correspondence →
  `other` (these are already excluded terms in the keyword lexicon's non-methods-pubtype list, but
  the bulk pool is a blunt keyword match, so plenty still slip through to manual review).

### Suggested edge-case guidance
- **"AI" as an ambiguous abbreviation.** Biomedical literature uses "AI" for things that have
  nothing to do with artificial intelligence — Avian Influenza, Artificial Insemination, Aortic
  Insufficiency, among others. The bulk-match query searches for the literal phrase "artificial
  intelligence" (not the bare abbreviation "AI"), so this shouldn't flood the queue, but if you hit
  one, it's `wrong-domain-non-bio`, not a query bug.
- **A "clear negative" candidate (Step 14 — fetched specifically for *not* mentioning AI/ML terms
  at all) that still reads like it's adjacent to ML (e.g. heavy classical statistics).** Still
  negative unless it actually crosses into the Positive criteria above — proximity to ML isn't the
  bar, application is. If Step 14b's screening flagged it (a BM25 score above the validated
  threshold despite the exclusion query), that's exactly the kind of case worth a second look
  before confirming — see the inline warning in the Curate app.

### Your notes & examples (add as you go)
<!-- e.g. 2026-08-05, PMID 87654321: marked negative, wrong-domain-non-bio (AI = Artificial Insemination) -->

---

## Skipped

**Rule of thumb:** you're deferring judgment because you haven't fully assessed the paper yet —
this is about *your* time/context right now, not a judgment about the paper's content.

### Use when
- You're short on time and want to come back to it later.
- Full text isn't available and you want to revisit once it might be (rather than force a decision
  now).
- The abstract is garbled, corrupted, or in a language you can't currently assess.

### The key distinction from Undeterminable
Skip = "haven't looked closely enough yet." Undeterminable = "looked closely — including full text
if available — and genuinely can't tell." If you're not sure which one applies, ask: *did I
actually make a real effort to decide?* If not, it's Skip.

### Your notes & examples (add as you go)
<!-- e.g. 2026-08-05: skipping non-English abstracts for now, will revisit with translation later -->

---

## Undeterminable

This one already has a project-wide policy — see `ROADMAP.md`'s **"Undeterminable handling
policy"** section, reproduced here so it's not two sources of truth that can drift apart:

1. No forced resolution — an honest "undeterminable" beats a coin-flip guess.
2. Distinct from Skipped (see above) — use it only after actually looking, including full text if
   available.
3. Excluded from the classifier's train/val/test splits — it would only add label noise.
4. Retained as a dedicated calibration/routing validation set for Phase 6, once that exists.

### Suggested edge-case guidance
- Abstract is too vague/generic to tell whether a real ML method was applied or just claimed in
  passing.
- Full text isn't available (no PMCID), the abstract doesn't clarify enough on its own, **and**
  you've made a genuine effort (per the Skip-vs-Undeterminable distinction above).
- Conflicting signals within the same abstract — e.g. it mentions "our deep learning framework" in
  one sentence but reads like a pure literature review in structure everywhere else, and you can't
  resolve which is true without full text you don't have.

### Your notes & examples (add as you go)
<!-- e.g. 2026-08-05, PMID 11223344: no full text, abstract ambiguous between applying vs. citing a method -->

---

## Criteria changelog

Dated log of any time a rule in this file actually changed (not just got clarified/reworded) — so
you can decide later whether earlier decisions made under the old rule need a second pass.

- 2026-08-02: initial criteria drafted (this file created).
