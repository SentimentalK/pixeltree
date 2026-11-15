# Labeling dataset v1 — per-source statistics and labeling cost

## Source and protocol

- **What this covers:** the first labeled dataset (label set v1) of the detector project: 3,215 exported images with box labels, produced by a frontier model under the box convention in `box_convention_v1.md`, plus a QA and fix pass. The per-source and per-split table counts exported images after QA rejects and removals; the cost table is the ledger of all labeling calls.
- **Models and roles:** `label` = the first labeling pass (Claude Opus 5.5); `qa` = the review pass on a sample (Claude Sonnet 5.5); `fix` = the correction pass on images that QA flagged. Model IDs and invocation are in `labeling/README.md`.
- **Sources:** `atspi118` (screens from the accessibility-tree capture pipeline, Linux applications), `groundcua` (a public desktop screenshot set), `web121` (web pages). Splits: `train` and `exam` (held-out applications and sites; exam is not used for training).
- **Counting rules:**
  - "Applications" = number of distinct (source, application) pairs.
  - "Images" = exported images, after removing QA rejects and training images with fewer than 10 boxes.
  - "Excluded" = images removed from that split.
  - "Text-line share" = share of boxes labeled as a text line.
- **Cost basis:** the ledger records each call with the token usage and a price. Two billing paths exist: direct API calls and CLI sessions. **All costs are API-equivalent (priced at API rates); they are not billed amounts.** The total is the sum of both paths.
- **Sample size:** 3,215 images, 168 applications or sites in total, 231,604 boxes.

## Results

**Table source_split.** Images, applications and boxes per source and split.

| Source | Split | Images | Applications | Boxes | Boxes per image (mean) | Text-line share | Excluded |
|---|---|---|---|---|---|---|---|
| atspi118 | train | 1031 | 65 | 55621 | 53.95 | 30.7% | 0 |
| atspi118 | exam | 258 | 17 | 15762 | 61.09 | 29.3% | 0 |
| groundcua | train | 1707 | 72 | 146139 | 85.61 | 24.0% | 0 |
| web121 | train | 174 | 11 | 11915 | 68.48 | 30.6% | 0 |
| web121 | exam | 45 | 3 | 2167 | 48.16 | 20.8% | 0 |
| Total | train | 2912 | 148 | 213675 | 73.38 | 26.1% | 0 |
| Total | exam | 303 | 20 | 17929 | 59.17 | 28.3% | 0 |
| Total | all | 3215 | 168 | 231604 | 72.04 | 26.3% | 0 |

**Table cost.** Labeling cost by billing path and role, in API-equivalent US dollars.

| Billing path | Role | Calls | API-equivalent cost (USD) |
|---|---|---|---|
| API | label | 429 | 86.4831 |
| API | qa | 33 | 2.3553 |
| API | fix | 22 | 7.6591 |
| CLI sessions | label | 3503 | 835.9178 |
| CLI sessions | qa | 874 | 96.5023 |
| CLI sessions | fix | 37 | 15.8273 |
| Total | – | 4898 | 1044.7449 |

Per role across both paths (sums of the rows above): label 922.4009 USD over 3,932 calls; qa 98.8576 USD over 907 calls; fix 23.4864 USD over 59 calls.

Derived: 1,044.74 USD / 3,215 exported images = 0.3250 USD per image (0.32496), labelling + QA + fix; the paper writes "about $0.32".

## Notes

- Exclusion reasons: QA rejects (dropped from training and exam); GroundCUA portrait screens (dropped from training only); images with fewer than 10 boxes (dropped from training; kept in the exam list). The per-application breakdown is not included here.
- The table counts are exported-image counts, so they do not equal the number of labeling calls: one image can have several calls (a whole-image pass, tile passes, QA and fix).
- The API-equivalent prices are the ledger's prices at the time of labeling; they are not invoices.
