---
name: update-classifier-model
description: Publish a newly trained topic-classifier model so run.sh, Docker Compose and Kubernetes can download it. Use when someone asks to train, publish, switch or roll back the classifier model.
---

# Publish a new classifier model

Model files never go into git. They live as release files in the private repository `mhd-riaz/news-bot-archive`, and `ml/models.toml` records where each one is and its SHA-256 checksum (a fingerprint that proves the file is unchanged).

## Steps

1. Train with the V4 trainer: `make -C ml ml4-train DATASET=<pool>`. It writes a new folder `ml/models/classifier/<model-id>/` with `bundle.joblib`, `manifest.json` and `model-card.md`. It refuses to overwrite a model that already exists.
2. Pack the three files and upload them to a NEW release in the private repository. Never upload to the public `news-bot` repository.

   ```sh
   tar -czf classifier-<model-id>.tar.gz -C ml/models/classifier/<model-id> bundle.joblib manifest.json model-card.md
   gh release create classifier-<model-id> classifier-<model-id>.tar.gz --repo mhd-riaz/news-bot-archive --title "Classifier <model-id>"
   ```

3. Add a `[[model]]` entry to `ml/models.toml` with the archive's SHA-256 and size and each file's SHA-256 (`shasum -a 256 <file>`).
4. Prove it: run `make -C ml models` in a fresh checkout, then `make -C ml models-check`.
5. Point the services at the new folder: `NEWSML_MODEL_DIR` in `deployment/compose/compose.yaml` and the classifier model settings in the Helm values files. Production also checks `NEWSML_MODEL_SHA256`, which is the SHA-256 of `bundle.joblib`.

## Rules

- Putting a model into production is the owner's decision (hard rule 5). Ask first.
- Scores against `data/labels/` measure agreement with AI-made labels, not proven correctness. Say so in the model card, and never call them human validation.
- Keep the old model's release, so a rollback is only a change of folder and checksum.
