"""Run one experiment and append it to the ledger.

v1 lost entire rounds of results between sessions because numbers lived in throwaway
scripts. Every run here appends a row recording the git sha, snapshot, config and
metrics, so a comparison table can always be rebuilt from disk.

Each run is scored three ways: the temporal validation split, and each publisher
holdout. The holdouts are not a final audit -- they are a column on every row, because
a model that leans on publisher style looks fine on validation and only fails there.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, evaluate, models
from .snapshot import Snapshot, _git_sha


@dataclass(frozen=True, slots=True)
class Setup:
    name: str
    model: str
    variant: str = "title_body"
    params: dict = field(default_factory=dict)
    note: str = ""

    @property
    def digest(self) -> str:
        payload = json.dumps(
            {"model": self.model, "variant": self.variant, "params": self.params},
            sort_keys=True,
        )
        return sha256(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Outcome:
    setup: Setup
    val: evaluate.Score
    holdouts: dict[str, evaluate.Score]
    fit_seconds: float
    predict_ms_per_doc: float
    n_train: int
    predictions: tuple[str, ...] = ()
    truth: tuple[str, ...] = ()

    def row(self, snapshot_id: str, git_sha: str) -> dict:
        return {
            "name": self.setup.name,
            "model": self.setup.model,
            "variant": self.setup.variant,
            "config_digest": self.setup.digest,
            "snapshot": snapshot_id,
            "git_sha": git_sha,
            "seed": config.SEED,
            "macro_f1": round(self.val.macro_f1, 4),
            "macro_f1_low": round(self.val.macro_f1_low, 4),
            "macro_f1_high": round(self.val.macro_f1_high, 4),
            "weighted_f1": round(self.val.weighted_f1, 4),
            "accuracy": round(self.val.accuracy, 4),
            **{f"holdout_{k}": round(v.macro_f1, 4) for k, v in self.holdouts.items()},
            "n_train": self.n_train,
            "n_val": self.val.n,
            "fit_seconds": round(self.fit_seconds, 2),
            "predict_ms_per_doc": round(self.predict_ms_per_doc, 4),
            "params": json.dumps(self.setup.params, sort_keys=True),
            "note": self.setup.note,
        }


def _labelled(snap: Snapshot) -> pd.DataFrame:
    frame = snap.frame
    return frame[frame["topic"].notna() & (frame["topic"] != config.UNSORTED)]


def run(snap: Snapshot, setup: Setup, *, holdouts: tuple[str, ...] | None = None) -> Outcome:
    frame = _labelled(snap)
    train = frame[frame["split"] == "train"]
    val = frame[frame["split"] == "val"]

    pipeline = models.build(setup.model, **setup.params)
    x_train = snap.texts(train, setup.variant)
    y_train = train["topic"].to_numpy()

    started = time.perf_counter()
    pipeline.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started

    x_val = snap.texts(val, setup.variant)
    started = time.perf_counter()
    predicted = pipeline.predict(x_val)
    predict_ms = (time.perf_counter() - started) * 1000 / max(len(x_val), 1)

    val_score = evaluate.score(
        val["topic"].to_numpy(), predicted, val["story_group_id"].to_numpy(), with_matrix=True
    )

    # Each holdout refits without one publisher, so the score answers "generalises to an
    # unseen masthead" rather than "was scored on a publisher it also trained on".
    holdout_scores: dict[str, evaluate.Score] = {}
    for publisher in holdouts if holdouts is not None else config.PUBLISHER_HOLDOUTS:
        fit_rows = frame[(frame["publisher"] != publisher) & (frame["split"] != "test")]
        held = frame[(frame["publisher"] == publisher) & (frame["split"] != "test")]
        if held.empty or fit_rows["topic"].nunique() < 2:
            continue
        other = models.build(setup.model, **setup.params)
        other.fit(snap.texts(fit_rows, setup.variant), fit_rows["topic"].to_numpy())
        holdout_scores[publisher] = evaluate.score(
            held["topic"].to_numpy(),
            other.predict(snap.texts(held, setup.variant)),
            held["story_group_id"].to_numpy(),
        )

    return Outcome(
        setup=setup,
        val=val_score,
        holdouts=holdout_scores,
        fit_seconds=fit_seconds,
        predict_ms_per_doc=predict_ms,
        n_train=len(train),
        predictions=tuple(predicted),
        truth=tuple(val["topic"]),
    )


def record(outcome: Outcome, snap: Snapshot, *, path: Path | None = None) -> None:
    path = path or config.LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = outcome.row(snap.snapshot_id, _git_sha(config.ML_ROOT.parent))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def ledger(path: Path | None = None) -> pd.DataFrame:
    path = path or config.LEDGER_PATH
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(l) for l in path.read_text().splitlines() if l.strip()])
