import numpy as np
import pytest

from newsmlv4 import train
from newsmlv4.serving import SidecarModel


def classifier(probabilities, cut=0.6):
    seen = []

    class Stub(train.V4Classifier):
        def probabilities(self, texts):
            seen.append(list(texts))
            return np.array(probabilities)

    model = Stub(
        folds=(), classes=np.array(["politics", "sport"], dtype=object), cut=cut,
        metadata={"model_version": "v4-test"},
    )
    return SidecarModel(model), seen


def test_input_text_is_the_title_and_lede_the_model_was_trained_on():
    model, _ = classifier([[0.5, 0.5]])

    text = model.input_text("  Rates \n held  ", "A  short\nsummary.", "The body is ignored.")

    assert text == "Rates held\nA short summary."


def test_input_text_falls_back_to_a_clipped_body_when_there_is_no_summary():
    model, _ = classifier([[0.5, 0.5]])

    lede = model.input_text("Title", "", "word " * 200).split("\n", 1)[1]

    assert len(lede) <= 400
    assert lede.endswith("word") and set(lede.split()) == {"word"}


def test_route_files_only_at_or_above_the_cut():
    model, _ = classifier([[0.1, 0.9], [0.55, 0.45], [0.4, 0.6]])

    labels, scores, filed = model.route(["a", "b", "c"])

    assert list(labels) == ["sport", "unsorted", "sport"]
    assert list(scores) == [0.9, 0.55, 0.6]
    assert list(filed) == [True, False, True]


def test_warm_up_runs_the_model_once():
    model, seen = classifier([[0.5, 0.5]])

    model.warm_up()

    assert len(seen) == 1 and len(seen[0]) == 1


def test_only_a_v4_classifier_is_accepted():
    with pytest.raises(TypeError, match="V4Classifier"):
        SidecarModel(object())
