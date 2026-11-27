"""Signal hygiene: remove what predicts the *publisher* rather than the *topic*.

This is not tidying. `Story continues below this ad` sits in 75% of Indian Express
bodies, and the Indian Express skews toward particular classes, so that phrase becomes a
predictor of those classes -- a relationship that is real in this sample and false in the
world. The same applies to place names in an India-heavy corpus, where city desks
oversupply crime and disaster until the model learns `Bengaluru -> crime_justice`.

Every rule is a switch and none is on by default. The brief's own warning applies: do
not blindly apply traditional NLP preprocessing, because news classification leans on
named entities and stemming destroys them. Each rule is measured, and kept only if it
helps the **publisher holdout more than validation** -- validation shares publishers with
training and so rewards the very shortcut we are trying to remove.

The spaCy pass is the expensive part, so it runs **once** and every policy is rendered
from the stored annotations.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import spacy
from spacy.language import Language

MODEL = "en_core_web_sm"

# ORG is deliberately never masked: ISRO, RBI and BCCI are genuine topic signal, whereas
# a politician's name is memorisation that will not survive the next election.
_PLACE = {"GPE", "LOC", "FAC"}
_NUMERIC = {"MONEY", "PERCENT", "DATE", "TIME", "CARDINAL", "ORDINAL", "QUANTITY"}
_KEEP_SURFACE = {"ORG", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"}


@dataclass(frozen=True, slots=True)
class ScrubPolicy:
    mask_person: bool = False
    mask_place: bool = False
    mask_numbers: bool = False
    lemmatise: bool = False

    @property
    def is_noop(self) -> bool:
        return not any((self.mask_person, self.mask_place, self.mask_numbers, self.lemmatise))

    def label(self) -> str:
        if self.is_noop:
            return "raw"
        on = [f for f in self.__dataclass_fields__ if getattr(self, f)]
        return "+".join(f.replace("mask_", "") for f in on)


def with_rule(policy: ScrubPolicy, rule: str, value: bool = True) -> ScrubPolicy:
    return replace(policy, **{rule: value})


def loader(model: str = MODEL) -> Language:
    """NER and lemmas only. The parser is the expensive part and nothing here needs it."""
    return spacy.load(model, exclude=["parser", "senter"])


# (surface, lemma, entity type, is-numeric). Deliberately a plain tuple: one pass over
# thousands of articles produces millions of these, and a class per token is not worth
# the memory.
Token = tuple[str, str, str, bool]


def annotate(
    texts: list[str],
    *,
    nlp: Language | None = None,
    batch_size: int = 128,
    n_process: int = 4,
) -> list[list[Token]]:
    nlp = nlp or loader()
    return [
        [(t.text, t.lemma_.lower(), t.ent_type_, bool(t.like_num)) for t in doc if not t.is_space]
        for doc in nlp.pipe(texts, batch_size=batch_size, n_process=n_process)
    ]


def render(tokens: list[Token], policy: ScrubPolicy, geography: frozenset[str] = frozenset()) -> str:
    parts: list[str] = []
    for surface, lemma, entity, numeric in tokens:
        if policy.mask_person and entity == "PERSON":
            parts.append("<PERSON>")
        elif policy.mask_place and (entity in _PLACE or surface.lower() in geography):
            parts.append("<PLACE>")
        elif policy.mask_numbers and (numeric or entity in _NUMERIC):
            parts.append("<NUM>")
        elif policy.lemmatise and entity not in _KEEP_SURFACE:
            parts.append(lemma)
        else:
            parts.append(surface)
    return " ".join(parts)


def render_all(
    annotated: list[list[Token]],
    policy: ScrubPolicy,
    geography: frozenset[str] = frozenset(),
) -> list[str]:
    return [render(tokens, policy, geography) for tokens in annotated]


def save(annotated: list[list[Token]], ids: list[str], path: Path) -> None:
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "article_id": ids,
            "surface": [[t[0] for t in doc] for doc in annotated],
            "lemma": [[t[1] for t in doc] for doc in annotated],
            "entity": [[t[2] for t in doc] for doc in annotated],
            "numeric": [[t[3] for t in doc] for doc in annotated],
        }
    ).to_parquet(path, compression="zstd", index=False)


def load(path: Path) -> tuple[list[str], list[list[Token]]]:
    import pandas as pd

    frame = pd.read_parquet(path)
    annotated = [list(zip(r.surface, r.lemma, r.entity, r.numeric)) for r in frame.itertuples()]
    return frame["article_id"].tolist(), annotated


def publisher_probe(texts: list[str], publishers: list[str], *, seed: int = 0) -> float:
    """How well can a model guess the masthead from the text?

    The score should FALL as cleaning improves. If it stays high, publisher fingerprints
    are still in the text and the classifier can ride them instead of learning topics.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(min_df=3, max_df=0.6, sublinear_tf=True)),
        ("clf", LogisticRegression(max_iter=1000, random_state=seed)),
    ])
    return float(cross_val_score(pipeline, texts, publishers, cv=3, scoring="accuracy").mean())
