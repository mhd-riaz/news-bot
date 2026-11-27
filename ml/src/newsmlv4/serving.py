"""Serve a V4 classifier behind the sidecar's /v1/classify contract (roadmap D19).

The sidecar was written for the body-aware v2 model. V4 reads the title and a lede,
never the full body, and `V4Classifier.route` returns no `filed` flag. This adapter
rebuilds the exact training input and presents the three-value `route` the sidecar
already expects, so the Go collector and its response contract do not change.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from newsml.load import LEDE_CHARS, _clip

from .train import V4Classifier, text_for

_WARM_UP = text_for("Warm-up article", "Loads the sentence encoder before the first request.")


class SidecarModel:
    """A `V4Classifier` that answers the way `newsmlv2.serve.Classifier` does."""

    def __init__(self, model: V4Classifier) -> None:
        if not isinstance(model, V4Classifier):
            raise TypeError(f"expected a V4Classifier, got {type(model).__name__}")
        self._model = model
        self.classes = model.classes
        self.cut = float(model.cut)
        self.metadata = model.metadata

    def input_text(self, title: str, summary: str, body: str) -> str:
        """The text V4 was trained on: the whitespace-collapsed title, then the lede.

        Training read `Article.lede`, which is the summary or, when there is none, the
        opening of the body, clipped at a word boundary. `_clip` is that same function.
        """
        return text_for(" ".join((title or "").split()), _clip(summary or body, LEDE_CHARS))

    def route(self, texts: Sequence[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(topic or `unsorted`, calibrated confidence, filed?) for each text."""
        labels, scores = self._model.route(texts)
        return labels, scores, scores >= self.cut

    def warm_up(self) -> None:
        """Load the sentence encoder now. The first call takes about 20 s on a laptop."""
        self._model.route([_WARM_UP])
