# Topic labels

This folder holds one list of news articles and the topic each one is about. We use it
to teach and to test the topic classifier (the program that puts each story under one
of 13 topics, such as `sport` or `politics`).

These labels were made by AI models and checked by automatic rules, so a score against them shows agreement with these labels, not proven correctness.

## Files

| File | What it is |
| --- | --- |
| `labels.jsonl` | The labels: one article per line, written as JSON. |
| `manifest.json` | Counts, plus SHA-256 fingerprints of `labels.jsonl` and of the files it was built from. A fingerprint is a long code that changes if even one byte changes. |
| `labelling-guide.md` | The guide for choosing a topic: the 13 topics, what each one covers, and the rules. |
| `reviewer-instructions.md` | How a person labels a new sheet of articles by hand. |

There is no article text here: no titles, summaries or links. The text belongs to the
news publishers, so it stays in the private database.

## Columns

| Column | Meaning |
| --- | --- |
| `article_id` | The article's ID in the news database. |
| `topic` | One of the 13 topic IDs in [`ml/taxonomy.yaml`](../../ml/taxonomy.yaml). |
| `split` | `train` if the row was used to teach the classifier, `test` if it was kept apart to score it. |
| `taxonomy_version` | The version of the topic list the label uses. Every row uses version 4. |
| `aliases` | Only on some rows: other IDs the same article has had, for example after the database was rebuilt. |

The `test` rows are the test set of model `v4-ai-072b01a9ceaf-hybrid_svc`. That test set
was opened once to score the model. Never train or tune anything on the `test` rows.

## Counts

| Topic | Train | Test | Total |
| --- | ---: | ---: | ---: |
| `business_economy` | 540 | 135 | 675 |
| `conflict_war` | 303 | 76 | 379 |
| `crime_justice` | 673 | 168 | 841 |
| `disaster_accident` | 382 | 95 | 477 |
| `education` | 404 | 101 | 505 |
| `entertainment_arts` | 548 | 137 | 685 |
| `environment_climate` | 366 | 92 | 458 |
| `health` | 429 | 107 | 536 |
| `politics` | 1,351 | 338 | 1,689 |
| `science_space` | 360 | 90 | 450 |
| `society_lifestyle` | 377 | 94 | 471 |
| `sport` | 456 | 114 | 570 |
| `technology` | 686 | 172 | 858 |
| **All** | **6,875** | **1,719** | **8,594** |

No row is `unsorted` (the label for "none of the 13"). 1,295 rows have `aliases`.

## Joining the labels to the article text

The text is in the `articles` collection of the private MongoDB database `news`. A
label's `article_id` (or one of its `aliases`) is the article's `_id` there, stored as
text. This Python example reads the text on your own machine; never commit the result.

```python
import json
from pymongo import MongoClient

articles = MongoClient("mongodb://127.0.0.1:27017")["news"]["articles"]
for line in open("data/labels/labels.jsonl", encoding="utf-8"):
    label = json.loads(line)
    ids = [label["article_id"], *label.get("aliases", [])]
    article = articles.find_one({"_id": {"$in": ids}}, {"title": 1, "summary": 1})
    if article is None:
        continue  # this copy of the database does not have the article
    print(label["topic"], label["split"], article["title"])
```

Some articles may be missing from your copy of the database. On 27 Nov 2026 the
laptop copy (252,510 articles) had 8,072 of the 8,594 labelled articles.

## How this folder was made

`ml/scripts/build_label_dataset.py` builds it from two private files that are not in
git: the pooled label set `v4-ai-pooled-20261122T000000Z` and the train/test split of
model `v4-ai-072b01a9ceaf`. It also stops if a count is wrong, if an article is in
both splits, or if an article from an older test set would be used for training.
Run `python3 scripts/build_label_dataset.py --check` from `ml/` to compare this folder
with those files again.

If people label articles by hand later, keep their labels in a separate file. Do not
mix them into `labels.jsonl`.
