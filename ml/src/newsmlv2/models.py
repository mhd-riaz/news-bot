"""The candidate models, as a registry rather than a hardcoded ladder.

Nothing here is chosen yet. Phase C establishes baselines, Phase E adds the tree and
embedding families, and the winner is whichever has the best interval -- with ties
broken toward the simpler model, because a tie means the complexity bought nothing.
"""

from __future__ import annotations

from typing import Callable

from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin, clone
from sklearn.decomposition import TruncatedSVD
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from .config import SEED


class _Head(BaseEstimator, TransformerMixin):
    """Keep the first n characters. Char n-grams over a full body are not affordable."""

    def __init__(self, chars: int = 600):
        self.chars = chars

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return [x[: self.chars] for x in X]

# Shared so every rung sees the same tokens and only the estimator differs.
_WORD = dict(
    lowercase=True,
    strip_accents="unicode",
    ngram_range=(1, 2),
    min_df=2,
    max_df=0.6,
    sublinear_tf=True,
)
_CHAR = dict(
    analyzer="char_wb",
    ngram_range=(3, 5),
    min_df=3,
    max_df=0.6,
    sublinear_tf=True,
    lowercase=True,
)


def _majority(**_) -> Pipeline:
    return Pipeline([("clf", DummyClassifier(strategy="prior", random_state=SEED))])


def _complement_nb(**kw) -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(**{**_WORD, **kw.get("vectoriser", {})})),
        ("clf", ComplementNB()),
    ])


def _tfidf_logreg(**kw) -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(**{**_WORD, **kw.get("vectoriser", {})})),
        ("clf", LogisticRegression(
            C=kw.get("C", 5.0),
            max_iter=2000,
            class_weight=kw.get("class_weight", "balanced"),
            random_state=SEED,
        )),
    ])


def _tfidf_linear_svc(**kw) -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(**{**_WORD, **kw.get("vectoriser", {})})),
        ("clf", LinearSVC(
            C=kw.get("C", 1.0),
            class_weight=kw.get("class_weight", "balanced"),
            random_state=SEED,
        )),
    ])


def _word_char_svc(**kw) -> Pipeline:
    """Word and character n-grams together.

    Character n-grams buy robustness to spelling and transliteration, which matters in a
    corpus mixing Indian and international mastheads. They are applied to the **first
    600 characters only**: char 3-5 grams over a full 4,000-character body generate tens
    of millions of features and dominate fitting time for signal the word features
    already carry. The headline and lede are where spelling variation actually matters.
    """
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(**{**_WORD, **kw.get("vectoriser", {})})),
            ("char", Pipeline([
                ("head", _Head(kw.get("char_chars", 600))),
                ("tfidf", TfidfVectorizer(**_CHAR)),
            ])),
        ])),
        ("clf", LinearSVC(
            C=kw.get("C", 1.0),
            class_weight=kw.get("class_weight", "balanced"),
            random_state=SEED,
        )),
    ])


class _StringLabels(BaseEstimator, ClassifierMixin):
    """Let XGBoost take the string classes every other estimator here accepts.

    XGBoost insists on contiguous integer labels, which would otherwise leak encoding
    into every call site and make the models non-interchangeable.
    """

    def __init__(self, estimator=None):
        self.estimator = estimator

    def fit(self, X, y):
        from sklearn.preprocessing import LabelEncoder

        self.encoder_ = LabelEncoder().fit(y)
        self.classes_ = self.encoder_.classes_
        self.estimator_ = clone(self.estimator)
        self.estimator_.fit(X, self.encoder_.transform(y))
        return self

    def predict(self, X):
        return self.encoder_.inverse_transform(self.estimator_.predict(X))

    def predict_proba(self, X):
        return self.estimator_.predict_proba(X)


def _dense(n_components: int, estimator, vectoriser: dict | None = None) -> Pipeline:
    """TF-IDF reduced to a dense space, then a tree model.

    Trees are never given the raw sparse matrix: with ~200k features and a few thousand
    rows, each split sees a near-empty column and the model spends its depth budget on
    noise. SVD (latent semantic analysis) compresses that into a few hundred dense
    components the trees can actually split on.
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(**{**_WORD, **(vectoriser or {})})),
        ("svd", TruncatedSVD(n_components=n_components, random_state=SEED)),
        ("clf", estimator),
    ])


def _svd_xgboost(**kw) -> Pipeline:
    from xgboost import XGBClassifier

    return _dense(
        kw.get("n_components", 256),
        _StringLabels(XGBClassifier(
            n_estimators=kw.get("n_estimators", 400),
            max_depth=kw.get("max_depth", 6),
            learning_rate=kw.get("learning_rate", 0.1),
            subsample=kw.get("subsample", 0.8),
            colsample_bytree=kw.get("colsample_bytree", 0.8),
            min_child_weight=kw.get("min_child_weight", 1),
            reg_lambda=kw.get("reg_lambda", 1.0),
            objective="multi:softprob",
            tree_method="hist",
            n_jobs=-1,
            random_state=SEED,
        )),
        vectoriser=kw.get("vectoriser"),
    )


def _svd_random_forest(**kw) -> Pipeline:
    return _dense(
        kw.get("n_components", 256),
        RandomForestClassifier(
            n_estimators=kw.get("n_estimators", 500),
            class_weight=kw.get("class_weight", "balanced"),
            n_jobs=-1,
            random_state=SEED,
        ),
        vectoriser=kw.get("vectoriser"),
    )


def _svd_extra_trees(**kw) -> Pipeline:
    return _dense(
        kw.get("n_components", 256),
        ExtraTreesClassifier(
            n_estimators=kw.get("n_estimators", 500),
            class_weight=kw.get("class_weight", "balanced"),
            n_jobs=-1,
            random_state=SEED,
        ),
        vectoriser=kw.get("vectoriser"),
    )


REGISTRY: dict[str, Callable[..., Pipeline]] = {
    "majority": _majority,
    "complement_nb": _complement_nb,
    "tfidf_logreg": _tfidf_logreg,
    "tfidf_linear_svc": _tfidf_linear_svc,
    "word_char_svc": _word_char_svc,
    "svd_xgboost": _svd_xgboost,
    "svd_random_forest": _svd_random_forest,
    "svd_extra_trees": _svd_extra_trees,
}


def build(name: str, **kw) -> Pipeline:
    if name not in REGISTRY:
        raise KeyError(f"unknown model {name!r}; have {sorted(REGISTRY)}")
    return REGISTRY[name](**kw)
