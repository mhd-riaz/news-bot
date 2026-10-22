"""Read the 13-class taxonomy and the gold labels.

Both are vendored into this package so ml-v2 builds without reaching into `../ml/`.
The label file is not committed, so its sha256 is the only integrity anchor tying a
snapshot to the labels it was built from -- every manifest records it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config


@dataclass(frozen=True, slots=True)
class Taxonomy:
    version: int
    classes: tuple[str, ...]
    descriptions: dict[str, str]
    excludes: dict[str, str]
    geography: frozenset[str]
    non_topical: frozenset[str]

    def __contains__(self, topic: str) -> bool:
        return topic in self.classes


def read_taxonomy(path: Path | None = None) -> Taxonomy:
    raw = yaml.safe_load((path or config.TAXONOMY_PATH).read_text(encoding="utf-8"))
    entries = raw.get("classes") or []
    return Taxonomy(
        version=int(raw.get("version", 0)),
        classes=tuple(sorted(e["id"] for e in entries)),
        descriptions={e["id"]: e.get("description", "") for e in entries},
        # `excludes` names the sibling a class is most often confused with. The measured
        # label noise sits on exactly these boundaries, so error analysis reads them.
        excludes={e["id"]: e.get("excludes", "") for e in entries},
        # Phase D0 uses these as a stoplist: place names are strong predictors inside
        # this India-heavy sample and near-useless outside it.
        geography=frozenset(raw.get("geography") or ()),
        non_topical=frozenset(raw.get("non_topical") or ()),
    )


def read_gold(path: Path | None = None) -> dict[str, str]:
    """article_id -> topic. One human label per article; later rows win."""
    labels: dict[str, str] = {}
    for line in (path or config.LABEL_PATH).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[row["article_id"]] = row["topic"]
    return labels


def trainable(labels: dict[str, str], taxonomy: Taxonomy) -> dict[str, str]:
    """Drop `unsorted` before anything counts classes.

    `unsorted` is the absence of a class, not a 14th class. It matters that this
    happens *first*: the class floor is derived as the smallest class present, so
    leaving 63 `unsorted` rows in would set the floor to 63 and start training it.
    """
    return {a: t for a, t in labels.items() if t != config.UNSORTED and t in taxonomy}


def abstention_set(labels: dict[str, str]) -> tuple[str, ...]:
    """The `unsorted` gold rows: a good model should decline to classify these."""
    return tuple(a for a, t in labels.items() if t == config.UNSORTED)
