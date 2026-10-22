"""Confidence and abstention. Each test encodes a way this goes quietly wrong."""

import math

import numpy as np

from newsmlv2 import confidence

CLASSES = np.array(["conflict_war", "politics", "sport"])


def _probabilities(rows: list[tuple[float, float, float]]) -> np.ndarray:
    return np.array(rows, dtype=float)


class TestCalibrationMetrics:
    def test_a_perfectly_calibrated_model_has_zero_error(self):
        probabilities = _probabilities([[0.0, 0.0, 1.0]] * 10)
        truth = np.array(["sport"] * 10)
        assert confidence.expected_calibration_error(probabilities, truth, CLASSES) == 0.0

    def test_confident_and_wrong_is_the_worst_case(self):
        probabilities = _probabilities([[0.0, 0.0, 1.0]] * 10)
        truth = np.array(["politics"] * 10)
        assert confidence.expected_calibration_error(probabilities, truth, CLASSES) == 1.0

    def test_brier_rewards_hedging_when_the_model_is_wrong(self):
        truth = np.array(["politics"] * 4)
        sure = _probabilities([[0.0, 0.0, 1.0]] * 4)
        hedged = _probabilities([[0.3, 0.3, 0.4]] * 4)
        assert confidence.brier(hedged, truth, CLASSES) < confidence.brier(sure, truth, CLASSES)


class TestCuts:
    def test_the_cut_is_the_lowest_that_holds_not_the_safest(self):
        # Six sport calls, the bottom two wrong. A cut at 0.70 keeps four at 100%.
        probabilities = _probabilities(
            [[0.05, 0.05, s] for s in (0.95, 0.90, 0.80, 0.70, 0.60, 0.55)]
        )
        truth = np.array(["sport"] * 4 + ["politics"] * 2)
        cut = confidence.fit_cuts(probabilities, truth, CLASSES,
                                  auto_precision=0.9, min_kept=4)["sport"]
        assert cut.auto == 0.70

    def test_a_class_that_never_reaches_the_target_abstains_instead_of_guessing(self):
        probabilities = _probabilities([[0.05, 0.05, s] for s in (0.99, 0.95, 0.90, 0.85)])
        truth = np.array(["politics"] * 4)
        cut = confidence.fit_cuts(probabilities, truth, CLASSES,
                                  auto_precision=0.9, review_precision=0.7,
                                  min_kept=2)["sport"]
        assert cut.forced_abstain and math.isinf(cut.auto)

    def test_a_class_nobody_predicts_is_not_silently_given_a_cut_of_zero(self):
        probabilities = _probabilities([[0.05, 0.90, 0.05]] * 4)
        truth = np.array(["politics"] * 4)
        assert confidence.fit_cuts(probabilities, truth, CLASSES)["sport"].forced_abstain


class TestRouting:
    def _cuts(self) -> dict[str, confidence.Cut]:
        return {
            "sport": confidence.Cut("sport", 0.50, 0.30, 0.95, 0.80, 100),
            "politics": confidence.Cut("politics", 0.80, 0.60, 0.91, 0.72, 100),
            "conflict_war": confidence.Cut("conflict_war", math.inf, math.inf,
                                           math.nan, math.nan, 40),
        }

    def test_each_class_is_judged_by_its_own_bar(self):
        probabilities = _probabilities([[0.1, 0.2, 0.7], [0.1, 0.7, 0.2]])
        routed = confidence.route(probabilities, CLASSES, self._cuts())
        # 0.70 clears sport's 0.50 outright but only reaches politics' review band.
        assert list(routed.bands) == [confidence.AUTO, confidence.REVIEW]

    def test_a_forced_abstainer_never_files_however_confident_it_looks(self):
        probabilities = _probabilities([[0.99, 0.005, 0.005]])
        routed = confidence.route(probabilities, CLASSES, self._cuts())
        assert routed.labels[0] == "unsorted" and routed.bands[0] == confidence.UNKNOWN

    def test_coverage_counts_review_only_when_asked(self):
        probabilities = _probabilities([[0.1, 0.2, 0.7], [0.1, 0.7, 0.2], [0.99, 0.005, 0.005]])
        routed = confidence.route(probabilities, CLASSES, self._cuts())
        assert routed.coverage() == 1 / 3
        assert routed.coverage(including_review=True) == 2 / 3
