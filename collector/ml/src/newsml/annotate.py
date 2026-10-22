"""Export articles for blind human labelling, and read the completed sheets back.

The gold set is the only thing every reported number rests on, so two properties
matter more than convenience:

* **Blind.** The sheet carries the title and summary and nothing else. No source,
  no URL, no proposed label. A labeller who sees "Wired" types `technology`
  without reading, and the feed URLs literally contain the section name, so
  either would leak the weak label into the gold set and turn the agreement
  study into a measurement of itself.
* **Reproducible.** The sample is drawn with a fixed seed from a fixed corpus, so
  the same command produces the same sheet.

One article per story group: labelling three copies of the same wire story costs
three times as much and yields one label's worth of information.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .labels import (
    Label,
    LabelSource,
    Taxonomy,
    from_categories,
    from_feed,
    from_publisher,
    is_geography_only,
)
from .load import Article

COLUMNS = ("article_id", "title", "summary", "label", "notes")
ADJUDICATION_COLUMNS = ("article_id", "title", "summary", "votes", "label", "notes")

# Excel guesses the encoding of a plain UTF-8 CSV and guesses wrong, mangling
# every non-ASCII character. The BOM is what stops that, and Sheets ignores it.
ENCODING = "utf-8-sig"

# Procedure, not definition. Each rule says which of two classes wins when both
# genuinely fit; none of them changes what a class means. That distinction is
# what lets these be added without bumping the taxonomy version and invalidating
# every label already assigned under it. Derived from the collisions the first
# rounds actually produced, not imagined in advance. The taxonomy went flat at
# v4 (see taxonomy.yaml), which retired the child-level rule about election
# machinery vs government business — both are `politics` now, so there is
# nothing left to break the tie between.
TIE_BREAKS = (
    "The political process beats its subject. A legislature, ministry, regulator or party "
    "acting is `politics`, even when the subject is the environment, defence or technology.",
    "An attack or military operation is `conflict_war`; prosecuting one in court is "
    "`crime_justice`; a minister's remarks about one are `politics`.",
)


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing wrong with a returned sheet, located precisely enough to fix."""

    sheet: str
    row: int
    article_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class Conflict:
    """An article the sheets labelled two ways, with the text that was shown."""

    article_id: str
    title: str
    summary: str
    votes: tuple[tuple[str, int], ...]

    @property
    def rendered_votes(self) -> str:
        return " | ".join(f"{topic} x{count}" for topic, count in self.votes)

    def crosses_groups(self, parent_of: dict[str, str]) -> bool:
        return len({parent_of.get(topic, topic) for topic, _ in self.votes}) > 1


def _representatives(articles: list[Article], group_of: dict[str, str] | None) -> list[Article]:
    """One article per story group, chosen by smallest id so it never varies."""
    if not group_of:
        return sorted(articles, key=lambda a: a.id)

    best: dict[str, Article] = {}
    for article in sorted(articles, key=lambda a: a.id):
        group = group_of.get(article.id, article.id)
        if group not in best:
            best[group] = article
    return [best[key] for key in sorted(best)]


def choose_sample(
    articles: list[Article],
    *,
    size: int,
    seed: int,
    group_of: dict[str, str] | None = None,
) -> list[Article]:
    """Draw a sample that covers every source rather than mirroring the corpus.

    Round-robin across sources, not proportional allocation. Proportional would
    hand ~17% of the sheet to one publisher and leave the small sources with two
    articles each, which is useless for deciding whether the taxonomy fits. The
    trade-off is that the sample over-represents small sources, so agreement
    measured on it is a per-source figure and not a corpus-wide rate.
    """
    pool = _representatives(articles, group_of)

    by_source: defaultdict[str, list[Article]] = defaultdict(list)
    for article in pool:
        by_source[article.source_id].append(article)

    rng = random.Random(seed)
    queues = {}
    for source_id in sorted(by_source):
        members = list(by_source[source_id])
        rng.shuffle(members)
        queues[source_id] = members

    chosen: list[Article] = []
    order = sorted(queues)
    while len(chosen) < size and any(queues[s] for s in order):
        for source_id in order:
            if not queues[source_id]:
                continue
            chosen.append(queues[source_id].pop())
            if len(chosen) >= size:
                break

    return sorted(chosen, key=lambda a: a.id)


def _cell(value: str) -> str:
    """Collapse whitespace so a multi-line summary stays one spreadsheet row."""
    return " ".join((value or "").split())


@dataclass(frozen=True, slots=True)
class TargetedSample:
    """A sheet built to fill specific classes, plus the accounting to prove it did."""

    articles: list[Article]
    retrieved_for: dict[str, str]
    shortfall: dict[str, int]
    quota: dict[str, int] = field(default_factory=dict)
    precision: dict[str, float] = field(default_factory=dict)

    @property
    def asked_for(self) -> Counter[str]:
        return Counter(self.retrieved_for.values())


def _leaf_classes(taxonomy: Taxonomy) -> list[str]:
    """Classes an annotator should actually reach for.

    A group that has children is a fallback for an article spanning two of them,
    so retrieving candidates *for* it would compete with its own children over
    the same articles and teach the model to prefer the vaguer label.
    """
    parents = {c.parent for c in taxonomy.classes if c.parent}
    return [c.id for c in taxonomy.classes if c.id not in parents]


def _with_topical_categories(article: Article, texts: dict[str, str], taxonomy: Taxonomy) -> str:
    """The retrieval text, with the publisher's own tags folded in.

    The tags are a strong hint about subject and they cost nothing to read, but
    only the topical ones: `categories` interleaves subject with place, and
    `india` or `chennai` outnumbers every real topic in this corpus. Including
    them would rank by *where* a story happened, which is the exact confusion the
    taxonomy keeps geography out of the class list to avoid.

    Nothing is hand-mapped. Because the seed articles carry their own tags too,
    a class centroid picks up whichever strings co-occur with it — so `badminton`
    pulls towards sport and `climate crisis` towards the environment without
    either ever being added to `category_map`.
    """
    tags = [
        value
        for raw in (article.categories or ())
        if (value := str(raw).casefold().strip())
        and value not in taxonomy.geography
        and value not in taxonomy.non_topical
    ]
    return " ".join([texts.get(article.id, article.title), *tags])


def _from_unlabelled_desk(article: Article, taxonomy: Taxonomy) -> bool:
    """Whether this article's source carries no topic label of its own.

    `feed_topics` and `publisher_topics` are keyed by the source names in
    `configs/sources.yaml`, so everything not in either is a general national
    desk or a city desk — the feeds that file whatever happened today.
    """
    return article.source_name not in taxonomy.feed_topics and article.source_name not in taxonomy.publisher_topics


def _desk_prior(
    seeds: dict[str, str], desks: dict[str, bool], base: float, strength: float = 5.0
) -> defaultdict[str, float]:
    """For each class, how often a human found it on a source with no topic label.

    Measured, not assumed. On the round-1 gold set this separates sharply:
    `politics_protest` 100%, `disaster_accident` 86%, `crime` 79% — against
    `tech_consumer` 2% and `business_markets` 4%. Which is the whole reason the
    rare classes are rare. A section feed hands out its own weak label, so the
    classes with a section are already served and the ones without are hiding in
    the general desks.

    Smoothed towards the corpus-wide rate so a class with fourteen examples
    cannot claim 100% and turn a preference into a hard filter.
    """
    seen: defaultdict[str, list[bool]] = defaultdict(list)
    for article_id, topic in seeds.items():
        if article_id in desks:
            seen[topic].append(desks[article_id])
    return defaultdict(
        lambda: base,
        {
            topic: (sum(flags) + strength * base) / (len(flags) + strength)
            for topic, flags in seen.items()
        },
    )


def _retrieval_precision(
    seeds: dict[str, str],
    ranking_text: dict[str, str],
    described: dict[str, str],
    vectorizer,
    desks: dict[str, bool],
    prior: defaultdict[str, float],
    topics: Iterable[str],
    *,
    eval_share: float = 0.25,
    seed: int = 0,
) -> dict[str, float]:
    """How often the top of a class's ranking really is that class.

    Measured on the labels already in hand rather than assumed: hold out a
    quarter of them, rank that quarter using centroids built from the other
    three, and count how many of a class's top n are truly it.

    This is what turns a balanced *ask* into a balanced *result*. Retrieval runs
    around half right, so asking for the exact shortfall returns about half the
    labels the class needs, and the classes with the weakest retrieval — the rare
    ones — fall furthest behind. Exactly the imbalance the sheet exists to fix.

    Self-calibrating on purpose: precision climbs as the gold set grows, so a
    hard-coded table would silently over-ask for ever.
    """
    import numpy as np

    train, check = split_gold(seeds, eval_share=eval_share, seed=seed)
    held = [a for a in check if a in ranking_text]
    if len(held) < 20:
        return {}

    matrix = vectorizer.transform([ranking_text[a] for a in held])
    on_desk = np.array([desks.get(a, False) for a in held])
    truth = [check[a] for a in held]
    counts = Counter(truth)

    measured: dict[str, float] = {}
    for topic in topics:
        # Under three held-out examples a rate is one article's worth of luck.
        if (n := counts.get(topic, 0)) < 3:
            continue
        query = [ranking_text[a] for a, t in train.items() if t == topic and a in ranking_text]
        if described.get(topic):
            query.append(described[topic])
        if not query:
            continue
        centroid = np.asarray(vectorizer.transform(query).mean(axis=0)).ravel()
        if not centroid.any():
            continue
        share = prior[topic]
        score = (matrix @ centroid) * np.where(on_desk, share, 1.0 - share)
        top = np.argsort(-score)[:n]
        measured[topic] = sum(truth[i] == topic for i in top) / n
    return measured


def choose_targeted_sample(
    articles: list[Article],
    texts: dict[str, str],
    taxonomy: Taxonomy,
    *,
    per_class: int,
    seeds: dict[str, str],
    group_of: dict[str, str] | None = None,
    random_share: float = 0.15,
    max_similarity: float = 0.3,
    min_precision: float = 0.25,
    exclude: Iterable[str] | None = None,
    seed: int = 0,
) -> TargetedSample:
    """Go looking for the rare classes instead of hoping a random draw finds them.

    Round 1 drew at random and returned 20 `conflict_war` labels out of 1,200,
    because that is roughly how often armed conflict appears in the feeds. No
    larger random sample fixes that: at 1.7% prevalence, 150 labels of it needs
    9,000 draws from a corpus that holds about 7,400. So each class states how
    many labels it still wants, and the articles most like the ones it already
    has are retrieved to fill the gap.

    `per_class` is a target to *end up at*, not a number to hand out. A class
    already there is sampled zero times, and a class below it retrieves more
    candidates than the gap — enough that the labels it yields close the gap once
    retrieval's own error rate is paid for. See `_retrieval_precision`.

    The ranking is nearest-centroid over TF-IDF: a class is represented by the
    average of the articles a human already filed under it, with its taxonomy
    description mixed in so a class with few examples still has a direction, and
    the publisher's own topical tags folded into the text on both sides.
    Classes take turns rather than each taking its whole quota in one go, so a
    common class cannot drain the pool before a rare one has been served.

    That text score is then weighted by where the class actually turns up. A
    section feed such as "The Guardian — Sport" already supplies its own weak
    label, so the classes with a section are the ones already served, and the
    ones without are hiding in the general and city desks: 100% of round 1's
    `politics_protest` and 86% of its `disaster_accident` came from a source with
    no topic label, against 2% of `tech_consumer`. See `_desk_prior`.

    `random_share` keeps a plain random slice in the sheet. Without it the sheet
    only ever contains articles that already look like something we know, the
    labels drift towards confirming the retrieval, and prevalence becomes
    impossible to estimate from any later round.

    `max_similarity` stops one heavily-covered event filling a class's quota.
    Retrieval alone returned four rewrites of the same TikTok privacy settlement
    for `tech_security`; near-duplicate grouping missed them because each
    newsroom reworded the headline. Four copies of one story cost four times the
    attention and teach the model one story.

    The default is measured, not guessed: on this corpus, rewrites of one story
    score 0.25 to 0.52 against each other, while genuinely different articles on
    the same subject sit near 0.18. Anything above 0.3 is therefore far more
    likely to be the same event than a second example of the class.

    Retrieval is a *suggestion of where to look*, never a label: the returned
    articles are shuffled into one sheet and `retrieved_for` is kept out of it,
    because an annotator shown a proposed class will agree with it.

    `exclude` skips a class entirely regardless of how short of `per_class` it
    is — for a class where more labels are already known not to help (see
    `society_lifestyle`'s round 3 result), asking again just spends an
    annotator's attention on a question the evidence already answered.
    """
    if per_class < 1:
        raise ValueError("per_class must be at least 1")
    if not 0.0 <= random_share < 1.0:
        raise ValueError(f"random_share must sit in [0, 1), got {random_share}")
    if not 0.0 < min_precision <= 1.0:
        raise ValueError(f"min_precision must sit in (0, 1], got {min_precision}")

    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    pool = [a for a in _representatives(articles, group_of) if a.id not in seeds]
    if not pool:
        return TargetedSample([], {}, {})
    described = {c.id: (c.description or "") for c in taxonomy.classes}
    have = Counter(seeds.values())
    # A class already at the target is finished: it is sampled zero times, so the
    # whole sheet goes to the classes that are actually short.
    excluded = set(exclude or ())
    quota = {
        topic: per_class - have.get(topic, 0)
        for topic in _leaf_classes(taxonomy)
        if topic not in excluded and per_class - have.get(topic, 0) > 0
    }

    ranking_text = {a.id: _with_topical_categories(a, texts, taxonomy) for a in articles}
    corpus = [ranking_text[a.id] for a in pool]
    vectorizer = TfidfVectorizer(
        lowercase=True, strip_accents="unicode", ngram_range=(1, 2), min_df=2, sublinear_tf=True
    )
    pool_matrix = vectorizer.fit_transform(corpus)

    desks = {a.id: _from_unlabelled_desk(a, taxonomy) for a in articles}
    base = (sum(desks.values()) / len(desks)) if desks else 0.5
    prior = _desk_prior(seeds, desks, base)
    pool_is_desk = np.array([desks.get(a.id, False) for a in pool])

    precision = _retrieval_precision(
        seeds, ranking_text, described, vectorizer, desks, prior, list(quota), seed=seed
    )
    typical = float(np.median(list(precision.values()))) if precision else 1.0
    # The floor doubles as the cap on the over-ask: no class may retrieve more
    # than 1/min_precision candidates per label it still needs.
    wanted = {
        topic: int(np.ceil(gap / max(precision.get(topic, typical), min_precision)))
        for topic, gap in quota.items()
    }

    seeds_by_topic: defaultdict[str, list[str]] = defaultdict(list)
    for article_id, topic in seeds.items():
        if (text := ranking_text.get(article_id)) and topic in wanted:
            seeds_by_topic[topic].append(text)

    ranked: dict[str, list[int]] = {}
    for topic in wanted:
        # The description alone is a weak query, so it only carries a class that
        # has almost no examples to average.
        query = [*seeds_by_topic[topic], described[topic]] if described[topic] else seeds_by_topic[topic]
        if not query:
            continue
        centroid = np.asarray(vectorizer.transform(query).mean(axis=0)).ravel()
        if not centroid.any():
            continue
        similarity = (pool_matrix @ centroid) / (np.linalg.norm(centroid) or 1.0)
        # Posterior, loosely: how well the text matches, times how often this
        # class turns up on that kind of source at all.
        share = prior[topic]
        ranked[topic] = list(np.argsort(-(similarity * np.where(pool_is_desk, share, 1.0 - share))))

    # Scarcest first, so when two classes want the same article the one with
    # fewer existing labels gets it — but a class represented only by its
    # one-line description ranks the pool near-randomly, so it waits until the
    # classes with real examples have claimed their best matches.
    order = sorted(ranked, key=lambda t: (not seeds_by_topic[t], have.get(t, 0), t))
    cursor = dict.fromkeys(order, 0)
    filled: Counter[str] = Counter()
    retrieved_for: dict[str, str] = {}
    picked_rows: defaultdict[str, list[int]] = defaultdict(list)
    taken: set[int] = set()

    def retells_one_already_picked(index: int, topic: str) -> bool:
        if not (picked := picked_rows[topic]):
            return False
        # TF-IDF rows are L2-normalised, so the dot product is the cosine.
        return float((pool_matrix[index] @ pool_matrix[picked].T).toarray().max()) > max_similarity

    while any(filled[t] < wanted[t] for t in order):
        progressed = False
        for topic in order:
            if filled[topic] >= wanted[topic]:
                continue
            positions = ranked[topic]
            while cursor[topic] < len(positions):
                candidate = positions[cursor[topic]]
                if candidate in taken or retells_one_already_picked(candidate, topic):
                    cursor[topic] += 1
                    continue
                break
            if cursor[topic] >= len(positions):
                continue
            index = positions[cursor[topic]]
            taken.add(index)
            picked_rows[topic].append(index)
            retrieved_for[pool[index].id] = topic
            filled[topic] += 1
            progressed = True
        if not progressed:
            break

    rng = random.Random(seed)
    if random_share:
        spare = [i for i in range(len(pool)) if i not in taken]
        rng.shuffle(spare)
        for index in spare[: round(len(taken) * random_share / (1 - random_share))]:
            taken.add(index)
            retrieved_for[pool[index].id] = "random"

    chosen = sorted((pool[i] for i in taken), key=lambda a: a.id)
    shortfall = {t: wanted[t] - filled[t] for t in wanted if filled[t] < wanted[t]}
    return TargetedSample(chosen, retrieved_for, shortfall, quota, precision)


def write_sheets(
    articles: list[Article],
    out_dir: Path,
    *,
    shards: int = 1,
    overlap: int = 0,
    seed: int = 0,
) -> list[Path]:
    """Write one CSV per annotator, with an optional shared overlap block.

    The overlap is what makes inter-annotator agreement measurable: the same
    articles appear in every sheet, so disagreement between two people is
    visible. Without it there is no way to tell a hard taxonomy from a careless
    annotator.
    """
    if shards < 1:
        raise ValueError("shards must be at least 1")
    overlap = max(0, min(overlap, len(articles)))

    shared = articles[:overlap]
    rest = articles[overlap:]

    buckets: list[list[Article]] = [[] for _ in range(shards)]
    for index, article in enumerate(rest):
        buckets[index % shards].append(article)

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for index, bucket in enumerate(buckets, start=1):
        rows = sorted({a.id: a for a in [*shared, *bucket]}.values(), key=lambda a: a.id)
        # Shuffle so the shared block is not an identifiable run at the top,
        # which would invite treating it differently from the rest.
        random.Random(seed + index).shuffle(rows)

        path = out_dir / (f"labels-{index:02d}.csv" if shards > 1 else "labels.csv")
        with path.open("w", encoding=ENCODING, newline="") as handle:
            writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
            writer.writerow(COLUMNS)
            for article in rows:
                writer.writerow([article.id, _cell(article.title), _cell(article.lede), "", ""])
        written.append(path)

    return written


def write_guide(taxonomy: Taxonomy, path: Path, *, overlap: int = 0) -> Path:
    """Generate the annotator's instructions from the taxonomy definitions.

    Generated rather than hand-written so the humans and any other labeller are
    answering the same question, from one source of truth.
    """
    lines = [
        "# Labelling guide",
        "",
        f"Taxonomy version {taxonomy.version}. Generated from `ml/taxonomy.yaml` — do not edit by hand.",
        "",
        "Fill the **`label`** column with exactly one id from the table below.",
        "Leave `notes` for anything that felt wrong; it is read, not ignored.",
        "",
        "## How to choose",
        "",
        "Pick the one class the article is most about from the table below. The list is fixed —",
        "13 classes, one level, no finer subdivision beneath any of them — so every article gets",
        "exactly one id and there is no group-vs-specific judgement call to make.",
        "",
        "## Rules",
        "",
        "1. Label what the article is **about**, not where it happened. "
        "A Karnataka election story is `politics`, not a geography.",
        f"2. If it fits none of them, or you genuinely cannot tell, write `{taxonomy.unsorted}`. "
        "A forced guess is worse than an honest blank — it becomes silent noise no one can find later.",
        "3. Judge only from the title and summary shown. Do not search for the article. "
        "That is what the model sees, so that is what the label has to be based on.",
        "4. Pick the **dominant** subject when two apply, and say so in `notes`.",
        "5. Format is not subject. An opinion piece about cricket is still `sport`.",
        *(f"{number}. {rule}" for number, rule in enumerate(TIE_BREAKS, start=6)),
        "",
        "## Classes",
        "",
        "| id | covers | does not cover |",
        "| --- | --- | --- |",
    ]
    for group in taxonomy.groups:
        lines.append(f"| `{group.id}` | {group.description} | {group.excludes or '—'} |")
    lines.append(f"| `{taxonomy.unsorted}` | Anything else, or genuinely unclear. | — |")

    if overlap:
        lines += [
            "",
            "## Why some rows repeat across sheets",
            "",
            f"{overlap} articles appear in every sheet on purpose. Comparing how differently "
            "two people labelled the same article is what tells us whether the classes are "
            "well defined. Do not coordinate on them.",
        ]

    lines += [
        "",
        "## Returning the sheet",
        "",
        "Keep the `article_id` column exactly as it is — it is how labels are matched back.",
        "Do not add, remove or reorder rows. Save as CSV, keeping UTF-8 encoding.",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_sheet(
    path: Path,
    taxonomy: Taxonomy,
    *,
    known_ids: frozenset[str] | None = None,
    annotator: str = "",
) -> tuple[list[Label], list[Problem]]:
    """Parse a completed sheet, accepting only labels the taxonomy defines.

    A spreadsheet round-trip is lossy in ways that are easy to miss: autocorrect
    capitalises, autocomplete substitutes a neighbouring value, and a stray row
    gets sorted. Everything is checked rather than assumed.
    """
    allowed = taxonomy.ids | {taxonomy.unsorted}
    labels: list[Label] = []
    problems: list[Problem] = []
    seen: set[str] = set()

    with path.open("r", encoding=ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ("article_id", "label") if c not in (reader.fieldnames or [])]
        if missing:
            return [], [Problem(path.name, 0, "", f"sheet is missing column(s): {', '.join(missing)}")]

        for number, row in enumerate(reader, start=2):
            article_id = (row.get("article_id") or "").strip()
            raw = (row.get("label") or "").strip()

            if not article_id:
                problems.append(Problem(path.name, number, "", "blank article_id"))
                continue
            if article_id in seen:
                problems.append(Problem(path.name, number, article_id, "duplicate row for this article"))
                continue
            seen.add(article_id)

            if known_ids is not None and article_id not in known_ids:
                problems.append(Problem(path.name, number, article_id, "article_id is not in the corpus"))
                continue
            if not raw:
                continue  # not yet labelled; reported as a count, not an error

            resolved = taxonomy.canonical(raw) or (taxonomy.unsorted if raw.casefold() == taxonomy.unsorted else None)
            if resolved is None or resolved not in allowed:
                problems.append(Problem(path.name, number, article_id, f"not a taxonomy class: {raw!r}"))
                continue

            labels.append(Label(article_id, resolved, LabelSource.HUMAN, annotator or path.stem))

    return labels, problems


def disagreements(labels: list[Label]) -> dict[str, set[str]]:
    """Articles two annotators labelled differently, and what they each chose."""
    by_article: defaultdict[str, set[str]] = defaultdict(set)
    for label in labels:
        by_article[label.article_id].add(label.topic)
    return {article: topics for article, topics in by_article.items() if len(topics) > 1}


def read_gold(path: Path) -> dict[str, str]:
    """The written gold set as `{article_id: topic}`.

    Where an article is still unadjudicated it has more than one line and the
    last one read wins. That is arbitrary, and deliberately so: an unresolved
    disagreement should be resolved by a person, not averaged by a function.
    """
    gold: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            gold[row["article_id"]] = row["topic"]
    return gold


def split_gold(
    gold: dict[str, str], *, eval_share: float = 0.25, seed: int = 0
) -> tuple[dict[str, str], dict[str, str]]:
    """Divide the human labels into a slice that teaches and a slice that scores.

    Stratified by topic, because the rare classes are the entire reason the gold
    set was collected: a uniform draw would hand every `conflict_war` label to
    one side and leave the class either untaught or unscored.

    Returns `(train, eval)` for `build(gold=..., holdout=...)`. They are disjoint
    by construction, but near-duplicate containment is `build`'s job, not this
    function's — story groups are not known until the corpus has been read.
    """
    if not 0.0 < eval_share < 1.0:
        raise ValueError(f"eval_share must sit strictly between 0 and 1, got {eval_share}")

    by_topic: defaultdict[str, list[str]] = defaultdict(list)
    for article_id, topic in gold.items():
        by_topic[topic].append(article_id)

    rng = random.Random(seed)
    train: dict[str, str] = {}
    scoring: dict[str, str] = {}
    for topic in sorted(by_topic):
        members = sorted(by_topic[topic])
        rng.shuffle(members)
        # A class with a single label teaches rather than scores: one article is
        # not a measurement, but it is still an example.
        cut = int(len(members) * eval_share)
        for article_id in members[:cut]:
            scoring[article_id] = topic
        for article_id in members[cut:]:
            train[article_id] = topic

    return train, scoring


def read_sheet_texts(paths: Iterable[Path]) -> dict[str, tuple[str, str]]:
    """The title and summary exactly as the labeller saw them, keyed by article.

    Taken from the sheets rather than re-read from MongoDB so adjudication needs
    no database, and so a ruling is made on the same text the disputed labels
    were made on even if the corpus has since been re-cleaned.
    """
    texts: dict[str, tuple[str, str]] = {}
    for path in paths:
        with Path(path).open("r", encoding=ENCODING, newline="") as handle:
            for row in csv.DictReader(handle):
                article_id = (row.get("article_id") or "").strip()
                if article_id and article_id not in texts:
                    texts[article_id] = (row.get("title") or "", row.get("summary") or "")
    return texts


def conflicts(labels: list[Label], texts: dict[str, tuple[str, str]]) -> list[Conflict]:
    """Every disputed article, most-chosen label first so a majority is visible."""
    tally: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for label in labels:
        tally[label.article_id][label.topic] += 1

    disputed: list[Conflict] = []
    for article_id, counts in sorted(tally.items()):
        if len(counts) < 2:
            continue
        title, summary = texts.get(article_id, ("", ""))
        votes = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        disputed.append(Conflict(article_id, title, summary, votes))
    return disputed


def write_adjudication_sheet(disputed: list[Conflict], path: Path) -> Path:
    """One row per disputed article, showing what was chosen and how often.

    The competing labels are shown on purpose. Blindness protects the first pass;
    adjudication is the opposite job, ruling on a disagreement that is already
    known. `label` is left blank even where one option has a clear majority: a
    pre-filled ruling is a ruling nobody made.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(ADJUDICATION_COLUMNS)
        for conflict in disputed:
            writer.writerow([
                conflict.article_id,
                _cell(conflict.title),
                _cell(conflict.summary),
                conflict.rendered_votes,
                "",
                "",
            ])
    return path


@dataclass(frozen=True, slots=True)
class Agreement:
    """How well the weak signals match the humans. The ceiling on Phase 3."""

    gold_count: int
    covered: int
    exact: int
    same_group: int
    wrong_group: int
    no_weak_label: int
    geography_only: int
    examples: tuple[tuple[str, str, str], ...]

    @property
    def coverage(self) -> float:
        return self.covered / self.gold_count if self.gold_count else 0.0

    @property
    def group_agreement(self) -> float:
        return (self.exact + self.same_group) / self.covered if self.covered else 0.0


def weak_vs_gold(gold: dict[str, str], articles: dict[str, Article], taxonomy: Taxonomy) -> Agreement:
    """Compare every weak signal against the human label.

    This is the number Phase 3 cannot exceed: a classifier trained on weak labels
    inherits their error. Measured at the *group* level as well as the exact
    class, because a publisher prior can only ever name a group, so scoring it on
    exact-child match would understate it for a reason that is not its fault.
    """
    parent_of = {c.id: (c.parent or c.id) for c in taxonomy.classes}

    exact = same_group = wrong = no_weak = geo_only = 0
    examples: list[tuple[str, str, str]] = []

    for article_id, truth in sorted(gold.items()):
        article = articles.get(article_id)
        if article is None:
            continue

        weak = (
            from_feed(article, taxonomy)
            or from_publisher(article, taxonomy)
            or from_categories(article, taxonomy)
        )
        if weak is None:
            if is_geography_only(article, taxonomy):
                geo_only += 1
            else:
                no_weak += 1
            continue

        if weak.topic == truth:
            exact += 1
        elif parent_of.get(weak.topic, weak.topic) == parent_of.get(truth, truth):
            same_group += 1
        else:
            wrong += 1
            examples.append((truth, weak.topic, article.title[:64]))

    return Agreement(
        gold_count=len(gold),
        covered=exact + same_group + wrong,
        exact=exact,
        same_group=same_group,
        wrong_group=wrong,
        no_weak_label=no_weak,
        geography_only=geo_only,
        examples=tuple(examples[:10]),
    )
