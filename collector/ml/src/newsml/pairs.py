"""Calibrating the near-duplicate threshold from labelled evidence.

The 0.72 Jaccard cut in `neardup` was derived from the LSH banding — the S-curve
for 16 bands of 8 rows is steep near (1/16)^(1/8) — and never measured against a
person's judgement of whether two articles are the same story. Only 38 of 7,539
stories fold, which is implausibly few for a corpus this heavy in PTI/ANI wire
copy, so the number is probably wrong and nobody has checked.

Checking it needs labels, and labelling the whole candidate set would be waste:
a pair scoring 0.95 is the same story and a pair scoring 0.05 is not, and nobody
learns anything by confirming either. **The boundary region is the only part in
doubt**, so that is the only part sampled.

The sheet is blind — no score, no source, no article ids a labeller could look
up. Someone shown "0.71" will find a reason to agree with it, and the whole
point is an independent judgement to compare the score against.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

# The region worth a person's attention. Below the floor is obviously unrelated
# and above the ceiling is obviously the same copy; both were spot-checked when
# the grouping was built. Labelling either would spend attention confirming what
# is not in question.
BOUNDARY_LOW = 0.40
BOUNDARY_HIGH = 0.95

# Strata across that range, so the sheet covers the whole boundary rather than
# piling up wherever the corpus happens to be dense.
STRATA = 6

# Candidates for the sheet are generated with the banding that ships. They were
# once different: the sheet used 32 bands while grouping used 16, because 16 could
# not propose the pairs the threshold was in doubt about. Measuring that is what
# moved the shipping banding to 32, so the two now agree.
SHEET_BANDS = 32

ENCODING = "utf-8-sig"
COLUMNS = ("pair_id", "same_story", "title_a", "text_a", "title_b", "text_b", "notes")
YES = {"y", "yes", "1", "true", "same", "t"}
NO = {"n", "no", "0", "false", "different", "f"}


@dataclass(frozen=True, slots=True)
class Pair:
    """One candidate pair, and which stratum it was drawn from."""

    pair_id: str
    article_a: str
    article_b: str
    score: float
    stratum: int
    population: int = 1
    sampled: int = 1

    @property
    def weight(self) -> float:
        """How many pairs in the corpus this labelled pair stands for.

        Strata are sampled evenly but are not evenly populated, so an unweighted
        precision would over-count whichever band happened to be sparse.
        """
        return self.population / self.sampled if self.sampled else 0.0


@dataclass(frozen=True, slots=True)
class Score:
    """What one candidate threshold would do, judged against the labels."""

    threshold: float
    precision: float
    recall: float
    f1: float
    folded: float
    missed: float


def choose_pairs(
    candidates: tuple[tuple[str, str, float], ...],
    *,
    size: int = 100,
    low: float = BOUNDARY_LOW,
    high: float = BOUNDARY_HIGH,
    strata: int = STRATA,
    seed: int = 0,
) -> tuple[Pair, ...]:
    """Draw a stratified sample from the boundary region of the candidate set."""
    in_range = [(a, b, s) for a, b, s in candidates if low <= s < high]
    if not in_range:
        return ()

    width = (high - low) / strata
    buckets: dict[int, list[tuple[str, str, float]]] = {}
    for a, b, score in in_range:
        index = min(strata - 1, int((score - low) / width))
        buckets.setdefault(index, []).append((a, b, score))

    per_stratum = max(1, size // max(1, len(buckets)))
    rng = random.Random(seed)
    drawn: list[Pair] = []

    for index in sorted(buckets):
        members = sorted(buckets[index])
        take = min(per_stratum, len(members))
        for a, b, score in rng.sample(members, take):
            drawn.append(
                Pair(
                    pair_id="",
                    article_a=a,
                    article_b=b,
                    score=score,
                    stratum=index,
                    population=len(members),
                    sampled=take,
                )
            )

    # Shuffle before numbering, so pair_id order carries no signal about score.
    rng.shuffle(drawn)
    return tuple(
        Pair(
            pair_id=f"p{number:03d}",
            article_a=pair.article_a,
            article_b=pair.article_b,
            score=pair.score,
            stratum=pair.stratum,
            population=pair.population,
            sampled=pair.sampled,
        )
        for number, pair in enumerate(drawn, start=1)
    )


def write_sheet(
    pairs: tuple[Pair, ...],
    titles: dict[str, str],
    texts: dict[str, str],
    out_dir: Path,
) -> tuple[Path, Path]:
    """Write the blind sheet and, separately, the key that decodes it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "pairs.csv"
    key = out_dir / "pairs-key.jsonl"

    with sheet.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(COLUMNS)
        for pair in pairs:
            writer.writerow(
                [
                    pair.pair_id,
                    "",
                    _cell(titles.get(pair.article_a, "")),
                    _cell(texts.get(pair.article_a, "")),
                    _cell(titles.get(pair.article_b, "")),
                    _cell(texts.get(pair.article_b, "")),
                    "",
                ]
            )

    with key.open("w", encoding="utf-8", newline="\n") as handle:
        for pair in pairs:
            handle.write(
                json.dumps(
                    {
                        "pair_id": pair.pair_id,
                        "article_a": pair.article_a,
                        "article_b": pair.article_b,
                        "score": round(pair.score, 6),
                        "stratum": pair.stratum,
                        "population": pair.population,
                        "sampled": pair.sampled,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    return sheet, key


GUIDE = """# Near-duplicate labelling guide

Generated by `newsml export-pairs` — do not edit by hand.

## What you are doing, and why

A news collector pulls {sources} feeds into one place. When a wire agency like PTI or
Reuters files a story, a dozen papers run it — each with its own headline, its own trim,
its own opening line. To a reader they are obviously one story. To software they are
{count} different documents.

The system has a detector that tries to spot these. It compares the wording of two
articles and produces a similarity score, then treats anything above a cut-off as the
same story. **Nobody has ever checked where that cut-off should be.** It was worked out
from the maths of the matching algorithm, never against a person's judgement, and it is
currently folding far fewer stories than the amount of syndication suggests it should.

Your answers are what sets it. Each row is one pair the detector thinks *might* be the
same story. You say whether it is. From your answers we can measure, for every possible
cut-off, how often it would be right — and pick the one that is.

The pairs you have are deliberately the hard ones. The obvious matches and the obvious
non-matches were left out, because confirming those teaches us nothing.

## What to do

For each row, read the two articles and put one letter in **`same_story`**:

- **`y`** — these are the same story.
- **`n`** — these are different stories.
- **leave it blank** if you genuinely cannot tell. A blank is treated as unanswered and
  ignored. A guess is treated as evidence, and quietly moves the cut-off to the wrong
  place. Blank is always better than a coin flip.

Use **`notes`** for anything that felt wrong or was hard to call. Notes get read.

## The one question to ask

> Are these two pieces reporting **the same event**, or two different events?

Not "are they about the same topic". Two separate murders in the same city are the same
topic and different stories. Say `n`.

## Rules

1. **Rewording does not matter.** Different headline, different first sentence, one
   longer than the other, one naming a person the other does not — still `y` if it is
   the same event being reported.
2. **A different day is a different story.** Recurring items with a template — daily gold
   or fuel prices, horoscopes, market wraps, "today's headlines" — look almost identical
   because the wording *is* almost identical. Check the date and the numbers. Two
   instalments of the same daily feature are `n`.
3. **A later development is a different story.** First report of a crash, then the
   casualty figure, then the inquiry — these are separate stories about one event. Only
   say `y` when both pieces are reporting the *same* moment.
4. **A live blog or video version of a story is still that story.** A `Live:` or `Watch:`
   prefix on otherwise matching copy is `y`.
5. **Different productions are different pieces.** A video and a podcast built from the
   same feature, or an article and its own photo gallery, are `n` — they are separate
   things that happen to share a subject.
6. **Judge only from what is on the sheet.** Do not search for the articles. The detector
   sees the headline and the opening only, so your answer has to be based on the same.
7. If two rows look like each other, that is fine. Judge each on its own.

## Returning the sheet

Keep the `pair_id` column exactly as it is — it is how answers are matched back.
Do not add, remove or reorder rows. Save as CSV, keeping UTF-8 encoding.
There are **{count}** rows, and that is the whole set: every borderline pair in the
corpus, not a sample. So each blank row is genuinely missing evidence, not one of many.
"""


def write_guide(path: Path, *, count: int, sources: int = 97) -> Path:
    """Write the annotator's guide next to the sheet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(GUIDE.format(count=count, sources=sources), encoding="utf-8")
    return path


def read_key(path: Path) -> tuple[Pair, ...]:
    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return tuple(
        Pair(
            pair_id=row["pair_id"],
            article_a=row["article_a"],
            article_b=row["article_b"],
            score=float(row["score"]),
            stratum=int(row["stratum"]),
            population=int(row.get("population", 1)),
            sampled=int(row.get("sampled", 1)),
        )
        for row in rows
    )


@dataclass(frozen=True, slots=True)
class Filled:
    """A returned sheet: the rulings, the annotator's notes, and anything unreadable."""

    judgements: dict[str, bool]
    notes: dict[str, str]
    problems: tuple[str, ...]


def read_judgements(path: Path) -> Filled:
    """Read the filled sheet. An unanswered row is not a 'no'; it is unanswered."""
    judgements: dict[str, bool] = {}
    notes: dict[str, str] = {}
    problems: list[str] = []

    with path.open(encoding=ENCODING, newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            pair_id = (row.get("pair_id") or "").strip()
            answer = (row.get("same_story") or "").strip().casefold()
            if not pair_id:
                continue
            if note := (row.get("notes") or "").strip():
                notes[pair_id] = note
            if answer in YES:
                judgements[pair_id] = True
            elif answer in NO:
                judgements[pair_id] = False
            elif answer:
                problems.append(f"{path.name}:{number} {pair_id} — unreadable answer {answer!r}")

    return Filled(judgements=judgements, notes=notes, problems=tuple(problems))


def calibrate(
    pairs: tuple[Pair, ...],
    judgements: dict[str, bool],
    *,
    grid: tuple[float, ...] = tuple(round(0.40 + 0.02 * i, 2) for i in range(28)),
) -> tuple[Score, ...]:
    """Score every candidate threshold against the labelled pairs.

    Counts are weighted by stratum, because the sample is even across the
    boundary and the corpus is not. `folded` and `missed` are expressed as
    weighted pair counts: how many real pairs a threshold would join, and how
    many true duplicates it would leave apart.

    Everything here is conditional on the boundary region. A pair scoring above
    the ceiling is not in this sample and is not claimed to be measured.
    """
    labelled = [p for p in pairs if p.pair_id in judgements]
    if not labelled:
        return ()

    duplicates = sum(p.weight for p in labelled if judgements[p.pair_id])

    scores: list[Score] = []
    for threshold in grid:
        folded = [p for p in labelled if p.score >= threshold]
        joined = sum(p.weight for p in folded)
        correct = sum(p.weight for p in folded if judgements[p.pair_id])

        precision = correct / joined if joined else 0.0
        recall = correct / duplicates if duplicates else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(
            Score(
                threshold=threshold,
                precision=precision,
                recall=recall,
                f1=f1,
                folded=joined,
                missed=duplicates - correct,
            )
        )

    return tuple(scores)


def _cell(value: str) -> str:
    """One line of plain text. A newline inside a cell breaks some spreadsheets."""
    return " ".join((value or "").split())
