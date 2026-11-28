---
name: update-classifier-model
description: Publish a newly trained topic-classifier model so run.sh, Docker Compose and Kubernetes can download it. Use when someone asks to train, publish, switch or roll back the classifier model.
---

# Publish a new classifier model

Model files never go into git. Each model is one `.tar.gz` archive in the owner's public Google Drive folder, so anyone can download it without signing in. A backup copy of each archive is a release in the private repository `mhd-riaz/news-bot-archive`. `ml/models.toml` records where each archive is and its SHA-256 checksum (a fingerprint that proves the file is unchanged).

## Steps

1. Train with the V4 trainer: `make -C ml ml4-train DATASET=<pool>`. It writes a new folder `ml/models/classifier/<model-id>/` with `bundle.joblib`, `manifest.json` and `model-card.md`. It refuses to overwrite a model that already exists.
2. Pack the three files. The Drive folder is public, so the archive must hold only the model and its notes, never article text (hard rule 11).

   ```sh
   tar -czf classifier-<model-id>.tar.gz -C ml/models/classifier/<model-id> bundle.joblib manifest.json model-card.md
   ```

3. The owner uploads the archive into the Drive folder in a web browser; only the owner can add files there. Keep a backup copy as a NEW release in the private repository. Never upload to the public `news-bot` repository.

   ```sh
   gh release create classifier-<model-id> classifier-<model-id>.tar.gz --repo mhd-riaz/news-bot-archive --title "Classifier <model-id>"
   ```

4. Add a `[[model]]` entry to `ml/models.toml` with `url = "https://drive.usercontent.google.com/download?id=<file-id>&export=download&confirm=t"`, the archive's SHA-256 and size, and each file's SHA-256 (`shasum -a 256 <file>`). The file ID is the part between `/d/` and `/view` in the file's Drive link.
5. Prove it: run `make -C ml models` in a fresh checkout without signing in to anything, then `make -C ml models-check`.
6. Point the services at the new model: `NEWSML_MODEL_DIR` in `deployment/compose/compose.yaml`, the classifier model settings in the Helm values files, and in `deployment/compose/coolify.compose.yml` the model name in the start command, `NEWSML_MODEL_DIR` and the default checksum. Production refuses any `bundle.joblib` whose SHA-256 differs from that checksum.

## Rules

- Putting a model into production is the owner's decision (hard rule 5). Ask first.
- Scores against `data/labels/` measure agreement with AI-made labels, not proven correctness. Say so in the model card, and never call them human validation.
- Keep the old model's archive in Drive and its release, so a rollback is only a change of folder and checksum.
