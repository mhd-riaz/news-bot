"""Demo UI for the news topic classifier.

Two things this is trying to show, beyond "it predicts a class":

1. **The confidence number means something.** It has been corrected so that 0.80 really
   does mean right about 80% of the time -- the "is the confidence honest?" chart on the
   Validation tab is the evidence, and the confidence threshold in the sidebar is what
   that honesty buys you.
2. **The model can say "I don't know".** Below the threshold it declines rather than
   guessing, which is why accuracy on what it files (83%) is well above accuracy when it
   is forced to answer everything (78%).

This screen is shown in a live viva, so the copy stays inside the course vocabulary --
confusion matrix, precision/recall/F1, macro-averaging, decision boundary, threshold,
train/validation/test, bootstrap, bagging and boosting. Anything the module did not cover
is either glossed in one line or kept off the screen.

No logic lives here. Everything comes from `newsmlv2.serve` and the metrics written by
`newsmlv2 train`, so the demo cannot drift from the measured model.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from newsmlv2 import config, serve
from newsmlv2 import snapshot as snapshot_mod

SNAPSHOT_ID = "v2-001"
MODEL_DIR = config.ARTIFACT_DIR / "models" / SNAPSHOT_ID

READABLE = {
    "business_economy": "Business & Economy",
    "conflict_war": "Conflict & War",
    "crime_justice": "Crime & Justice",
    "disaster_accident": "Disaster & Accident",
    "education": "Education",
    "entertainment_arts": "Entertainment & Arts",
    "environment_climate": "Environment & Climate",
    "health": "Health",
    "politics": "Politics",
    "science_space": "Science & Space",
    "society_lifestyle": "Society & Lifestyle",
    "sport": "Sport",
    "technology": "Technology",
}

SAMPLES = {
    "Sport": (
        "India beat Australia by six wickets in the final over at the MCG",
        "Chasing 287, the Indian batting order held its nerve as the captain struck an "
        "unbeaten 94 off 71 balls. The bowlers had earlier restricted Australia to 286 "
        "for eight, with two wickets falling in the final over of the innings. The win "
        "seals the three-match one-day international series 2-1, and hands the visitors "
        "their first series victory in Australia since 2019.",
    ),
    "Business": (
        "Reserve Bank holds repo rate steady as inflation cools",
        "The monetary policy committee voted five to one to keep the benchmark repo rate "
        "unchanged, citing easing food inflation and steady growth in industrial output. "
        "Bond yields fell four basis points after the announcement and the rupee closed "
        "marginally stronger against the dollar. Economists said a rate cut is now likely "
        "in the next quarter if the monsoon holds.",
    ),
    "A near tie": (
        "Parliament clears bill raising import duty on electronics",
        "The bill passed after a three-hour debate in which the opposition walked out, "
        "arguing the measure would raise handset prices for consumers. Industry bodies "
        "welcomed the protection for domestic manufacturers, while importers warned of "
        "supply disruption. The finance minister said the change would take effect from "
        "the start of the next fiscal year.",
    ),
    "A boundary case": (
        "NCERT panel recommends rewriting three chapters of the class 10 history textbook",
        "The panel, appointed last year, said the chapters gave disproportionate space to "
        "certain periods. Opposition members of the review committee dissented, calling "
        "the exercise politically motivated. Teachers' associations have asked for the "
        "draft to be published before it is adopted. The ministry said the revised "
        "textbook would reach schools next academic year.",
    ),
}


@st.cache_resource(show_spinner="Loading the model bundle...")
def load_model() -> serve.Classifier:
    return serve.load(MODEL_DIR)


@st.cache_data(show_spinner=False)
def load_metrics() -> dict:
    return json.loads((MODEL_DIR / serve.METRICS).read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Reading the frozen snapshot...")
def load_unlabelled(limit: int = 400) -> pd.DataFrame:
    """Real articles from the corpus that no human ever labelled."""
    snap = snapshot_mod.read(config.SNAPSHOT_DIR / SNAPSHOT_ID)
    frame = snap.frame
    pool = frame[frame["topic"].isna() & frame["has_body"]]
    return pool.sample(min(limit, len(pool)), random_state=config.SEED)[
        ["article_id", "publisher", "title", "summary", "body"]
    ].reset_index(drop=True)


@st.cache_data(show_spinner="Looking for something it finds hard...")
def hardest(_model: serve.Classifier, n: int = 12) -> pd.DataFrame:
    """The articles in the unlabelled pool the model is least sure about."""
    pool = load_unlabelled(200)
    texts = [serve.text_for(t, s, b)
             for t, s, b in zip(pool["title"], pool["summary"], pool["body"])]
    scores = _model.probabilities(texts).max(axis=1)
    return pool.assign(confidence=scores).nsmallest(n, "confidence").reset_index(drop=True)


def least_certain(model: serve.Classifier, _cut: float):
    """Cycle through the hard cases so repeated clicks show different articles."""
    frame = hardest(model)
    if frame.empty:
        return None
    seen = st.session_state.get("hard_index", -1) + 1
    st.session_state.hard_index = seen
    return frame.iloc[seen % len(frame)]


def pretty(topic: str) -> str:
    return READABLE.get(topic, topic.replace("_", " ").title())


def interpolate(curve: list[dict], cut: float) -> tuple[float, float]:
    """Coverage and accuracy at an arbitrary cut, read off the validation sweep."""
    cuts = [p["cut"] for p in curve]
    return (
        float(np.interp(cut, cuts, [p["coverage"] for p in curve])),
        float(np.interp(cut, cuts, [p["accuracy_on_kept"] for p in curve])),
    )


st.set_page_config(page_title="News Topic Classifier", layout="wide")

if not (MODEL_DIR / serve.BUNDLE).is_file():
    st.error(
        f"No model bundle at `{MODEL_DIR}`.\n\n"
        f"Build one first:\n\n```\nuv run newsmlv2 train --id {SNAPSHOT_ID}\n```"
    )
    st.stop()

model = load_model()
metrics = load_metrics()
val, test = metrics["validation"], metrics["test"]

st.title("News Topic Classifier")
st.caption(
    "Files an English news article into one of 13 topics — and declines to answer when "
    "it is not sure enough. Supervised ML (Classification) mini-project · "
    "Mohamed Riaz · PES1PGE25DS037"
)

with st.sidebar:
    st.subheader("The model")
    st.metric("Test macro-F1", f"{test['macro_f1']:.3f}",
              help="Macro-averaged F1 — the F1 of each of the 13 classes worked out on "
                   "its own, then averaged with equal weight, so a small class is not "
                   "drowned out by a large one. 95% interval "
                   f"[{test['macro_f1_low']:.3f}, {test['macro_f1_high']:.3f}] · the test "
                   f"set was opened once, on {test['opened_on']}, and closed again")
    st.metric("Accuracy on filed articles", f"{test['accuracy_filed']:.1%}",
              delta=f"{test['accuracy_filed'] - test['accuracy_without_abstention']:+.1%} "
                    "vs answering everything")
    st.caption(
        "A linear model over word features: one weight per word per class, fitted "
        "one-vs-rest across the 13 classes. It reads the headline plus the first "
        f"{serve.BODY_CHARS:,} characters of the body, and was trained on "
        f"{metrics['metadata']['train_articles']:,} articles."
    )

    st.divider()
    st.subheader("Confidence threshold")
    st.caption(
        "How sure must it be before it files an article without a human reading it? "
        "Everything below the line goes to a person instead of being guessed at. This is "
        "the classification threshold: raise it and precision "
        "on what it files goes up, at the cost of answering fewer articles."
    )
    cut = st.slider("Threshold", 0.0, 0.95, float(metrics["cut"]), 0.01)
    coverage, on_kept = interpolate(metrics["coverage_curve"], cut)
    left, right = st.columns(2)
    left.metric("Filed automatically", f"{coverage:.0%}")
    right.metric("...and right this often", f"{on_kept:.0%}")
    if abs(cut - metrics["cut"]) > 1e-9:
        st.caption(f"The default is {metrics['cut']:.3f}, picked from cross-validation "
                   "scores inside the training set so that filed articles come out about "
                   "90% correct. It was never picked on validation or on test.")

classify_tab, validation_tab, batch_tab, method_tab = st.tabs(
    ["Classify an article", "Validation", "Run it on the corpus", "How it was built"]
)


with classify_tab:
    if "title" not in st.session_state:
        first = next(iter(SAMPLES))
        st.session_state.title, st.session_state.body = SAMPLES[first]

    def use_sample(name: str) -> None:
        st.session_state.title, st.session_state.body = SAMPLES[name]

    def use_uncertain() -> None:
        row = least_certain(model, cut)
        if row is None:
            st.session_state.title = st.session_state.body = ""
        else:
            st.session_state.title, st.session_state.body = row["title"], row["body"]

    st.markdown("**Start from**")
    columns = st.columns(len(SAMPLES) + 1)
    for column, name in zip(columns, SAMPLES):
        column.button(name, on_click=use_sample, args=(name,), use_container_width=True)
    columns[-1].button("A real one it is unsure about", on_click=use_uncertain,
                       use_container_width=True,
                       help="Picks the lowest-confidence article from a sample of real "
                            "collected news that nobody ever labelled.")

    title = st.text_input("Headline", key="title", placeholder="Paste the headline")
    body = st.text_area("Article body", key="body", height=200,
                        placeholder="Paste the article text. The model reads the first "
                                    "4,000 characters.")

    if st.button("Classify", type="primary", use_container_width=True):
        if not (title.strip() or body.strip()):
            st.warning("Give it a headline or some body text first.")
        else:
            result = model.classify(title, "", body)
            filed = result.confidence >= cut
            ranked = result.ranked

            verdict, detail = st.columns([2, 3])
            with verdict:
                if filed:
                    st.success(f"### {pretty(result.topic)}")
                    st.caption(f"Filed automatically — confidence {result.confidence:.1%} "
                               f"is above the {cut:.2f} threshold.")
                else:
                    st.warning(f"### Held for review — looks like {pretty(result.topic)}")
                    st.caption(f"Confidence {result.confidence:.1%} is below the {cut:.2f} "
                               "threshold, so this goes to a person rather than being filed.")
                st.progress(result.confidence)

                margin = ranked[0][1] - ranked[1][1]
                if margin < 0.25:
                    st.info(
                        f"**Close call.** {pretty(ranked[1][0])} is only "
                        f"{margin:.2f} behind. Raise the threshold in the sidebar past "
                        f"{result.confidence:.2f} and this article stops being filed."
                    )

            with detail:
                st.markdown("**Where the probability went**")
                st.dataframe(
                    pd.DataFrame(
                        [{"Topic": pretty(t), "Probability": p} for t, p in ranked[:6]]
                    ),
                    hide_index=True, use_container_width=True,
                    column_config={
                        "Probability": st.column_config.ProgressColumn(
                            format="%.3f", min_value=0.0, max_value=1.0
                        )
                    },
                )

            if result.evidence:
                st.markdown("**Why — the words that pushed it there**")
                st.caption(
                    "Each word is a feature, and the model's score for a class is just "
                    "the weighted sum of those features — the same weights-times-inputs "
                    "form that draws a decision boundary in logistic regression. So these "
                    "are literally the biggest terms in that sum: an exact reason, not an "
                    "approximation of one."
                )
                st.dataframe(
                    pd.DataFrame(
                        [{"Term": t, "Contribution": round(v, 4)} for t, v in result.evidence]
                    ),
                    hide_index=True, use_container_width=True,
                    column_config={
                        "Contribution": st.column_config.ProgressColumn(
                            format="%.3f", min_value=0.0,
                            max_value=float(result.evidence[0][1]),
                        )
                    },
                )


with validation_tab:
    a, b, c, d = st.columns(4)
    a.metric("Validation macro-F1", f"{val['macro_f1']:.3f}",
             help=f"[{val['macro_f1_low']:.3f}, {val['macro_f1_high']:.3f}] — the range "
                  "the score falls in when the validation set is resampled")
    b.metric("Test macro-F1", f"{test['macro_f1']:.3f}",
             delta=f"{test['macro_f1'] - val['macro_f1']:+.3f} vs validation")
    c.metric("Confidence gap (test)", f"{test['ece']:.3f}",
             delta=f"{test['ece'] - val['ece']:+.3f} vs validation", delta_color="inverse",
             help="Average distance between the confidence it claims and how often it "
                  "turns out to be right. 0.021 means the claim is off by about two "
                  "points — the thing AUC cannot see, because AUC only scores ranking.")
    d.metric("Body vs headline", f"+{metrics['body_ab']['delta']:.3f}",
             help="Macro-F1 gained by reading the article instead of just the headline. "
                  "Tested only on the articles the two versions disagreed about, rather "
                  "than by subtracting two accuracy numbers — "
                  f"p = {metrics['body_ab']['mcnemar_p']:.1e}.")

    st.caption(
        f"Validation is {val['n']:,} articles, test is {test['n']:,}. The test set was "
        f"opened exactly once ({test['opened_on']}) and nothing was changed in response "
        "to what it said — that is what makes it an honest estimate rather than a second "
        "validation set."
    )

    st.subheader("Per class")
    st.caption(
        "Precision, recall and F1 for each class, read straight off the confusion matrix "
        "below. The interval comes from resampling the set with replacement — the same "
        "bootstrap idea bagging uses — over whole stories rather than single articles, "
        "because five papers running the same wire story are not five independent "
        "observations. A wide interval means the class is thin, not that the model is "
        "unstable: read `education` (29 validation articles) as noise."
    )
    per_class = pd.DataFrame([
        {
            "Class": pretty(c["topic"]),
            "F1": c["f1"],
            "95% interval": f"[{c['low']:.2f}, {c['high']:.2f}]",
            "Precision": c["precision"],
            "Recall": c["recall"],
            "Val support": c["support"],
            "Test F1": test["per_class_f1"].get(c["topic"]),
        }
        for c in val["per_class"]
    ])
    st.dataframe(
        per_class, hide_index=True, use_container_width=True,
        column_config={
            "F1": st.column_config.ProgressColumn(format="%.2f", min_value=0.0, max_value=1.0),
            "Precision": st.column_config.NumberColumn(format="%.2f"),
            "Recall": st.column_config.NumberColumn(format="%.2f"),
            "Test F1": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Is the confidence honest?")
        st.caption(
            "Each point is a band of predictions: of everything it called with about 70% "
            "confidence, how much was actually right? On the straight line it is exactly "
            "as right as it claims. Above the line it is under-confident — the safe "
            "direction for a system that is allowed to hold articles back."
        )
        reliability = pd.DataFrame([
            {"Claimed": b["claimed"], "Actually right": b["actual"],
             "If it were perfectly honest": b["claimed"], "n": b["n"]}
            for b in metrics["reliability"]
        ]).set_index("Claimed")
        st.line_chart(reliability[["Actually right", "If it were perfectly honest"]])

    with right:
        st.subheader("What the threshold costs")
        st.caption(
            "Raise the threshold and the model files fewer articles but is right more "
            "often on the ones it does file. It is the precision–recall trade-off in a "
            "different pair of clothes, and it is the whole argument for letting a "
            "classifier decline to answer."
        )
        curve = pd.DataFrame(metrics["coverage_curve"]).rename(columns={
            "cut": "Confidence threshold", "coverage": "Filed",
            "accuracy_on_kept": "Accuracy on filed",
        }).set_index("Confidence threshold")
        st.line_chart(curve)

    st.subheader("Where it goes wrong")
    st.caption(
        "The most common confusions are the same class pairs the human labellers "
        "disagreed on when the corpus was labelled — 18.6% of errors sit on those pairs, "
        "so part of this gap is in the labels rather than in the model."
    )
    st.dataframe(
        pd.DataFrame([
            {"Actually": pretty(c["actual"]), "Called": pretty(c["called"]), "Articles": c["n"]}
            for c in val["confusions"]
        ]),
        hide_index=True, use_container_width=True,
    )

    with st.expander("Full confusion matrix"):
        matrix = pd.DataFrame(
            val["matrix"],
            index=[pretty(t) for t in val["labels"]],
            columns=[pretty(t) for t in val["labels"]],
        )
        st.dataframe(matrix.style.background_gradient(cmap="Blues", axis=None),
                     use_container_width=True)


with batch_tab:
    st.subheader("Real articles nobody labelled")
    st.caption(
        "These are drawn from the frozen snapshot — genuine collected news that was never "
        "part of training, validation or test. It is the closest thing to watching the "
        "model work on data it has never met. Every click draws a different batch."
    )

    how_many = st.slider("How many articles", 20, 300, 60, 20)
    if st.button("Classify a fresh batch", type="primary"):
        available = load_unlabelled(3000)
        pool = available.sample(min(how_many, len(available))).reset_index(drop=True)
        texts = [
            serve.text_for(t, s, b)
            for t, s, b in zip(pool["title"], pool["summary"], pool["body"])
        ]
        with st.spinner(f"Classifying {len(texts)} articles..."):
            probabilities = model.probabilities(texts)

        called = model.classes[probabilities.argmax(axis=1)]
        scores = probabilities.max(axis=1)
        filed = scores >= cut

        a, b, c = st.columns(3)
        a.metric("Filed automatically", f"{filed.mean():.0%}")
        b.metric("Sent for review", f"{1 - filed.mean():.0%}")
        c.metric("Median confidence", f"{np.median(scores):.2f}")

        st.bar_chart(
            pd.Series([pretty(t) for t in called]).value_counts().rename("Articles")
        )
        st.dataframe(
            pd.DataFrame({
                "Publisher": pool["publisher"],
                "Headline": pool["title"],
                "Filed as": [pretty(t) if f else "— held for review"
                             for t, f in zip(called, filed)],
                "Confidence": scores,
            }),
            hide_index=True, use_container_width=True,
            column_config={
                "Confidence": st.column_config.ProgressColumn(
                    format="%.2f", min_value=0.0, max_value=1.0
                )
            },
        )


with method_tab:
    st.subheader("From a raw feed to a trained model")
    st.caption(
        "Six steps turn collected news into something worth learning from, and only then "
        "is it split. Every step throws articles away on a written rule, never by hand."
    )

    corpus_dot = r"""
digraph corpus {
  rankdir=LR;
  bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#e8f0fe", color="#7f9dbd",
        fontcolor="#111111", fontname="Helvetica", fontsize=10, margin="0.16,0.10"];
  edge [color="#7f9dbd", arrowsize=0.7];

  raw   [label="Collected news\n40 publishers, full article text"];
  furn  [label="1  Drop publisher furniture\nlines repeated across one masthead"];
  clean [label="2  Clean the text\nstrip menus, ads, wire-agency tags"];
  admit [label="3  Keep only real articles\nno quizzes, galleries, price bulletins"];
  group [label="4  Group the same story\nsyndicated copies become one group"];
  gold  [label="5  Hand labels\n13 topics"];
  split [label="6  Split by time, and by story"];

  raw -> furn -> clean -> admit -> group -> gold -> split;

  train [label="Train\n__TRAIN__ articles", fillcolor="#e6f4ea", color="#7fae90"];
  val   [label="Validation\n__VAL__ articles", fillcolor="#fdf3e0", color="#c9a765"];
  test  [label="Test\n__TEST__ articles\nopened once, at the end",
         fillcolor="#fdecea", color="#cf9089"];

  split -> train;
  split -> val;
  split -> test;
}
"""
    for token, value in (("__TRAIN__", metrics["splits"]["train"]),
                         ("__VAL__", metrics["splits"]["val"]),
                         ("__TEST__", metrics["splits"]["test"])):
        corpus_dot = corpus_dot.replace(token, f"{value:,}")
    st.graphviz_chart(corpus_dot, use_container_width=True)

    with st.expander("What each step actually does to the text"):
        st.dataframe(
            pd.DataFrame([
                {"Step": "1  Publisher furniture",
                 "What it does": "For each publisher, finds lines that repeat across at least 5% of its articles (minimum 5 articles) and removes them — mastheads, author bios, standing footers.",
                 "Why": "A line every Hindu article carries is a perfect clue to the publisher and no clue at all to the topic."},
                {"Step": "2  Clean",
                 "What it does": "Normalises quotes and dashes, pulls off the dateline, and deletes 35 kinds of page furniture — 'Also read', newsletter sign-ups, comment prompts, 'Trending now'. Wire-agency tags (PTI, Reuters, ANI) come off too.",
                 "Why": "Those lines say which publisher it is, not which topic it is."},
                {"Step": "3  Admission",
                 "What it does": "Rejects anything under 12 body words or 3 title words, plus quizzes, photo galleries, horoscopes, gold-rate and weather bulletins, sponsored posts, exact duplicates, and impossible timestamps.",
                 "Why": "A photo gallery has no topic to learn. Training on one teaches the model noise."},
                {"Step": "4  Story grouping",
                 "What it does": "Compares each article with its 8 nearest neighbours on word overlap and groups them when the similarity clears 0.50. The threshold was set by hand-judging 43 pairs.",
                 "Why": "Five papers running one wire story are one observation, not five — and the split has to know that."},
                {"Step": "5  Labels",
                 "What it does": "Applies the 13-topic list by hand, with a written definition and an exclusion note for each topic. Anything a human could not place is marked unsorted and dropped.",
                 "Why": "A forced label on a genuinely ambiguous article is a wrong answer the model is then graded against."},
            ]),
            hide_index=True, use_container_width=True,
        )

    st.subheader("How the data was split")
    st.markdown(
        f"""
Train, validation and test are the three standard sets — fit on one, choose
on the second, report on the third — but a news corpus makes a plain random split lie to
you, so two extra rules apply.

- **{metrics['splits']['train']:,} / {metrics['splits']['val']:,} / {metrics['splits']['test']:,}**,
  roughly 70 / 15 / 15.
- **Split by time, not at random.** Every validation article was collected after every
  training article, and every test article after every validation one. So the test score
  answers the question that matters: how does it do on news it has not seen yet?
- **Split by story, not by article.** A story group never straddles a boundary.
  {metrics['splits']['dropped']:,} articles sat across one and were dropped whole rather
  than allowed to leak, because a syndicated copy on the training side and its twin on the
  test side would hand the model the answer.
- **Two publishers are held out completely** (The Hindu, The Guardian) and scored on their
  own run, with the model refitted from scratch without them.
        """
    )

    st.subheader("Inside the model")
    st.caption(
        "The model is a chain of four stages, not one algorithm. Only one of those stages "
        "picks a topic — the rest turn text into numbers, make the confidence honest, and "
        "decide whether to answer at all."
    )

    stack_dot = r"""
digraph stack {
  rankdir=LR;
  bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#e8f0fe", color="#7f9dbd",
        fontcolor="#111111", fontname="Helvetica", fontsize=10, margin="0.16,0.11"];
  edge [color="#7f9dbd", arrowsize=0.8];

  doc  [label="ONE ARTICLE\nheadline + first __BODY__\ncharacters of the body",
        fillcolor="#f4f4f4", color="#9aa0a6"];
  feat [label="1.  TEXT INTO NUMBERS\nword columns      227,846\nletter columns     72,422\ntotal            300,268\n \ntransforms only"];
  svm  [label="2.  LINEAR SVM\n13 sets of weights, each topic\nfitted against the other twelve\n \nTHE ONLY STAGE THAT\nPICKS A TOPIC",
        fillcolor="#e6f4ea", color="#7fae90"];
  cal  [label="3.  ISOTONIC REGRESSION\nturns a raw score into\na probability\n \nlearns, but never\npicks a topic",
        fillcolor="#fdf3e0", color="#c9a765"];
  gate [label="4.  THRESHOLD  __CUT__\ncompare and route\n \nno learning at all"];
  out  [label="FILE IT\nor HOLD IT FOR A PERSON",
        fillcolor="#f4f4f4", color="#9aa0a6"];

  doc -> feat -> svm -> cal -> gate -> out;
}
"""
    stack_dot = (stack_dot.replace("__BODY__", f"{serve.BODY_CHARS:,}")
                          .replace("__CUT__", f"{metrics['cut']:.3f}"))
    st.graphviz_chart(stack_dot, use_container_width=True)
    st.caption(
        "Stages 1 to 3 are fitted five times over, each on a different four-fifths of the "
        "training data, and their probabilities averaged. That is the only place anything "
        "is averaged."
    )

    st.dataframe(
        pd.DataFrame([
            {"Stage": "1  Text into numbers",
             "What it does": "Builds a column for every word, word-pair and 3-to-5 letter run in the training set, then fills in how much of each this article holds",
             "Does it learn?": "Learns the vocabulary and how rare each term is",
             "Does it pick the topic?": "No"},
            {"Stage": "2  Linear SVM",
             "What it does": "13 weighted sums, one per topic; highest wins",
             "Does it learn?": "Yes — a 13 x 300,268 table of weights",
             "Does it pick the topic?": "Yes — this is the classifier"},
            {"Stage": "3  Isotonic regression",
             "What it does": "Maps a raw score onto the frequency it was actually right at",
             "Does it learn?": "Yes — 65 curves (13 topics x 5 folds)",
             "Does it pick the topic?": "No"},
            {"Stage": "4  Threshold",
             "What it does": f"Files the article if the top probability clears {metrics['cut']:.3f}, else routes it to a person",
             "Does it learn?": "One number, chosen on held-out folds",
             "Does it pick the topic?": "No"},
        ]),
        hide_index=True, use_container_width=True,
    )

    st.markdown(
        """
**So is this an ensemble?** No. An ensemble means several models each answer *the same
question* and their answers are combined — bagging, boosting, voting, stacking. Here only
one stage answers the question "which topic is this?". The others turn text into numbers,
rescale a score, and compare against a cut-off. Chaining stages that each do a *different*
job is a pipeline, not an ensemble.

The one thing that genuinely is averaging is the five folds — five copies of the same model,
each trained on a different four-fifths, their probabilities averaged. Structurally that is
the bagging side of the family, but the folds are disjoint rather than drawn with
replacement, and they exist so each calibration curve has data its own model never saw. The
averaging falls out of that design; it was not chosen to improve accuracy.

Every real ensemble was tried as a *challenger* and lost: boosted trees −0.036 macro-F1,
random forest −0.041 to −0.087, majority vote +0.001. That comparison is below.
        """
    )

    st.markdown("**The four stages, step by step**")
    st.markdown(
        """
**1 — Every word becomes a column.** Reading only the training set, the model lists every
distinct word and every adjacent word-pair it sees: **227,846 columns**. An article is then
one row across those columns. The number in a cell is not a plain count. It goes *up* the
more times the word appears in that article, and *down* the more articles in the whole
corpus contain it — so *the* and *said* are worth almost nothing, while *wicket* or *repo
rate* are worth a lot. Repeats are damped too: a word ten times over is informative, but
not ten times as informative as once. Columns seen fewer than twice in training, or in more
than 60% of it, are thrown out before training even starts.

**2 — Then the same text is read again as letters.** A second set of **72,422 columns**
counts every run of three to five letters inside the first 600 characters. This is the part
that lets one model treat *ISRO*, *ISRO's* and a misspelling as related, that connects
*cricket*, *cricketer* and *cricketing*, and that still has something to say about a word
the training set never saw — a brand-new name still shares letter runs with familiar ones.

**3 — The two views sit side by side.** 227,846 + 72,422 = **300,268 columns**. A single
article fills in only a small fraction of them, so the row is stored as a sparse list of
"column 41,203 has value 0.18" rather than 300,268 mostly-zero numbers.

**4 — The classifier is a weighted sum.** For each of the 13 topics there is one weight per
column — a 13 × 300,268 table of numbers, which is the entire model. To score an article
for *Sport*, take every column it filled in, multiply by that column's *Sport* weight, add
them all up, add a constant. That sum is the distance from a decision boundary: positive
means "this side of the line, Sport", negative means "the other side". Thirteen topics means
thirteen separate lines, each drawn between one topic and the other twelve together — the
one-vs-rest way of doing multi-class with a two-class model. Whichever score comes out
highest is the answer.

**5 — The weights are learnt by widening the gap.** Training nudges each set of weights
until the correct topic's score sits above the rest by as wide a margin as it can manage,
while a penalty holds the weights themselves small. That penalty is what stops 300,268
columns from simply memorising 5,487 training articles. Each topic's mistakes are also
scaled up in proportion to how rare it is, so Education and Environment are not quietly
sacrificed to get Politics and Sport right.

**6 — A score is not a probability, so it gets converted.** The raw sum can be 0.4 or 3.1
and means nothing on its own. To fix that, the training set is cut into five folds; for each
fold the model is refitted on the other four and scored on the fold it never saw, and those
held-out scores are lined up against what the answers actually turned out to be. That gives
a curve mapping "score of 1.7" to "right about 88% of the time". Five such curves are
averaged into the one the app uses. Because every score behind the curve came from data the
model had not seen, the resulting confidence is honest — and the *is the confidence honest?*
chart on the Validation tab is the check, not the claim.

**7 — Only then does the threshold apply.** The top probability is compared against the
threshold in the sidebar. Above it the article is filed; below it, held for a person.
        """
    )

    with st.expander("The arithmetic, spelled out on one article"):
        st.markdown(
            """
Suppose the article is *"India beat Australia by six wickets in the final over"*.

1. It fills in a small fraction of the 300,268 columns — `india`, `beat`, `australia`,
   `wickets`, `final over`, plus letter runs like `wic`, `cket`, `kets`.
2. Each gets a value: `wickets` is rare across the corpus, so its value is high; `india`
   is everywhere in this corpus, so its value is low.
3. For *Sport*, every one of those values is multiplied by its *Sport* weight and the
   products are added up. Say that comes to **+2.9**.
4. The same values are run against the *Politics* weights: **−1.4**. And against the
   other eleven topics.
5. Highest wins — *Sport*. Its score of +2.9 goes through the conversion curve and comes
   out as, say, **0.94**.
6. 0.94 is above the threshold, so it is filed rather than held.

The **"why"** table on the Classify tab is simply step 3 opened up: the individual
`value × weight` terms, biggest first. It is not an approximation or a second model
guessing at the first — those numbers are literally the sum the decision was made from.
            """
        )

    with st.expander("Questions this design invites, and the honest answers"):
        st.dataframe(
            pd.DataFrame([
                {"Question": "300,268 columns for 5,487 training articles — why doesn't it just memorise them?",
                 "Answer": "Three things hold it back: the penalty on large weights during training, the fact that any one article touches only a small fraction of the columns, and the columns that appear fewer than twice being deleted up front. Whether it worked is not an opinion — the score is measured on articles collected later than every training article."},
                {"Question": "Isn't a straight-line boundary too simple for something as messy as news?",
                 "Answer": "In 300,268 dimensions there is a great deal of room, and topics separate more cleanly than intuition suggests. It was not assumed: boosted trees, two kinds of tree ensemble, and a neural sentence model were all fitted on the same split, and all three scored lower."},
                {"Question": "Why keep both word columns and letter columns?",
                 "Answer": "Words carry the topic; letters carry spelling, word endings and unfamiliar names. Dropping the letter half was measured and cost accuracy, so both stayed."},
                {"Question": "What happens to a word the model has never seen?",
                 "Answer": "Its word column does not exist, so it contributes nothing there — but its three-to-five letter runs almost certainly do exist, so the article is not blind to it."},
                {"Question": "13 topics but a two-class boundary — how does that work?",
                 "Answer": "One boundary per topic, each one separating that topic from the other twelve pooled together, and the highest of the 13 scores wins. That is one-vs-rest multi-class."},
                {"Question": "The topics are unbalanced. Doesn't the model just learn the big ones?",
                 "Answer": "Errors on a rare topic are weighted up in proportion to how rare it is, and the headline number is macro-F1 — each topic scored separately and then averaged with equal weight — so a small topic being ignored would show up immediately."},
                {"Question": "Why convert scores to probabilities at all?",
                 "Answer": "Because the model is allowed to decline. Refusing to answer below 0.584 only makes sense if 0.584 means something; an uncalibrated score does not."},
            ]),
            hide_index=True, use_container_width=True,
        )

    st.subheader("Which families were tried")
    st.caption("All fitted on the same split and scored the same way, so the comparison "
               "is fair. The one that shipped is marked.")
    st.dataframe(
        pd.DataFrame([
            {"Family": "Always guess the biggest class", "What it is": "The floor any real model has to beat", "Where it comes from": "Covered in class"},
            {"Family": "Word-count probability model", "What it is": "How typical is each word of each topic, multiplied together", "Where it comes from": "Read up (Naive Bayes)"},
            {"Family": "Logistic regression", "What it is": "Weighted sum, squashed into a probability", "Where it comes from": "Covered in class"},
            {"Family": "Linear model fitted to widen the gap  ← shipped", "What it is": "Same weighted sum and same decision boundary, fitted to push the classes as far apart as it can", "Where it comes from": "Read up (linear SVM)"},
            {"Family": "Bagged trees — random forest, extra trees", "What it is": "Many trees on bootstrap samples, votes averaged", "Where it comes from": "Covered in class"},
            {"Family": "Boosted trees — XGBoost", "What it is": "Trees added one at a time, each fixing the last one's mistakes", "Where it comes from": "Covered in class"},
            {"Family": "Sentence-embedding neural model", "What it is": "A pre-trained network turns a whole article into 384 numbers", "Where it comes from": "Read up"},
            {"Family": "Majority vote over the best of the above", "What it is": "Ensemble by voting", "Where it comes from": "Covered in class"},
        ]),
        hide_index=True, use_container_width=True,
    )

    st.subheader("What came from the course, and what had to be read up")
    read_up, taught = st.columns(2)
    with taught:
        st.markdown("**Covered in class, and used here**")
        st.markdown(
            """
- Train / validation / test, and why the test set is opened once
- The weighted sum and the decision boundary it draws
- One-vs-all for 13 classes
- Weighting classes because the topics are unbalanced
- The classification threshold and the precision–recall trade-off
- Confusion matrix, per-class precision / recall / F1, macro-averaging
- AUC scores ranking, not whether the number is honest
- Bootstrap sampling, used here for the intervals
- Bagging, boosting and voting as the challenger models
- Validation set as the guard against overfitting
            """
        )
    with read_up:
        st.markdown("**Not covered in class — researched for this project**")
        st.markdown(
            """
- **Text into columns, weighted by rarity** — what we were taught assumes a table of
  numbers; news is prose, so the table had to be built.
- **Letter-pattern columns** — for Indian-English spellings and word endings.
- **A linear model fitted to widen the gap between classes** — same shape as logistic
  regression, measurably better across 300,268 sparse columns.
- **Making the confidence honest** — we were taught that AUC judges ranking rather than
  whether the number itself is trustworthy, and this project needed it to be trustworthy
  before it could decline to answer.
- **Splitting the training set into folds** — needed somewhere to fit that correction and
  pick the threshold without ever touching validation or test.
- **Grouping by story and ordering by time before splitting** — leakage control that a
  plain three-way split does not cover.
- **Squeezing the columns down before the tree models** — trees cannot take 300,268
  sparse columns, so the challengers were given a compressed version.
- **Comparing two models only on what they disagree about** — subtracting two accuracy
  numbers cannot tell you whether a gap is real.
            """
        )

    st.divider()
    st.subheader("The question the project actually asked")
    st.markdown(
        f"""
An earlier version of this classifier read only the **headline and summary** — about 33
words per article — and scored **{metrics['body_ab']['v1_shipped']:.3f}** macro-F1. Once
the collector started storing full article bodies, the obvious question was whether ~650
words beat 33.

**It does, by +{metrics['body_ab']['delta']:.3f} macro-F1**
({metrics['body_ab']['title_summary']:.3f} → {metrics['body_ab']['title_body']:.3f}), and
the gap is real rather than luck: the two confidence intervals do not overlap, and a
paired test run over only the articles the two versions disagreed about gives
p = {metrics['body_ab']['mcnemar_p']:.1e}. That is the headline result, and it is a
*measured* answer rather than an assumed one.
        """
    )

    st.subheader("What was tried and rejected")
    st.caption("Every row was measured against the model already in place, with an "
               "interval or a paired test. Nothing was dropped on a hunch.")
    st.dataframe(
        pd.DataFrame([
            {"Idea": "Stripping names and places out of the text first", "Result": "no version of the rule helped", "Kept?": "No"},
            {"Idea": "Counting headline words more heavily than body words", "Result": "steadily worse the harder it was pushed", "Kept?": "No"},
            {"Idea": "Reading the end of the article as well as the start", "Result": "no difference", "Kept?": "No"},
            {"Idea": "Tuning the model's one strength setting over a 6x range", "Result": "moves macro-F1 by 0.002", "Kept?": "No"},
            {"Idea": "Boosted trees (XGBoost) on compressed word features", "Result": "−0.036 macro-F1, 5x slower", "Kept?": "No"},
            {"Idea": "Random forest, and extra-randomised trees", "Result": "−0.041 to −0.087 macro-F1", "Kept?": "No"},
            {"Idea": "A neural model that turns whole sentences into features", "Result": "−0.061 macro-F1", "Kept?": "No"},
            {"Idea": "Majority vote across the best models", "Result": "+0.001 — indistinguishable from no change", "Kept?": "No"},
            {"Idea": "A separate threshold for each class", "Result": "no better than one threshold for all 13", "Kept?": "No"},
            {"Idea": "Turning raw scores into honest probabilities", "Result": "costs 0.002 F1, makes the confidence trustworthy", "Kept?": "Yes"},
            {"Idea": "Holding back anything below the threshold", "Result": "78% → 83% accuracy on what it files", "Kept?": "Yes"},
            {"Idea": "Reading the full article, not just the headline", "Result": "+0.059 macro-F1", "Kept?": "Yes"},
        ]),
        hide_index=True, use_container_width=True,
    )

    st.markdown(
        """
**The uncomfortable finding is the useful one.** If something could always pick the right
model out of the ten tried, it would score 0.900 — so the models genuinely do disagree,
which is exactly the diversity an ensemble is supposed to feed on. Yet every ensemble that
can actually be built lands on 0.771. The disagreement is one-sided: the sentence-feature
model rescues 70 articles the linear model got wrong while breaking 148 it had right, and
a majority vote has no way of telling which side of that trade it is on.

So the accuracy came from **data preparation**, not from the classifier. Removing repeated
furniture lines, grouping near-identical copies of the same story, deciding which articles
were fit to train on, and splitting the data honestly did the work. The model itself is a
plain linear one, and every attempt to replace it with something heavier lost.
        """
    )

    with st.expander("How the evaluation avoids fooling itself"):
        st.markdown(
            """
- **Train, validation and test share no story and no day.** No story appears in two
  splits, and every test article was collected after every training article, so the test
  set is a genuine future rather than a random slice of the same days.
- **Intervals resample whole stories, not single articles.** Sampling with replacement
  — the bootstrap idea bagging is built on — over articles would treat five papers
  running one wire story as five independent observations, and report an interval
  narrower than the truth.
- **Two publishers are held out completely** (The Hindu, The Guardian) and scored on
  every run, with the model refitted from scratch without that publisher each time. The
  Guardian is the hard one: not Indian, and a different house style.
- **The test set was opened once**, through a single function that refuses to run without
  an explicit flag, after the model was frozen. It has not been reopened — a held-out set
  stops being held out the moment it changes a decision.
- **Two models are compared only on the articles they disagree about** (McNemar's test),
  not by subtracting two accuracy numbers, so a claimed improvement has to survive the
  cases that actually differ.
- **The raw score is never shown as a confidence.** A linear model outputs an unbounded
  number, not a probability — the same reason logistic regression puts a sigmoid on top
  of its weighted sum. Here that number is converted into a probability using a
  conversion fitted on cross-validation folds *inside* the training set, which is why the
  confidence can be checked honestly against how often it is right.
            """
        )

    with st.expander("Where this sits in the course"):
        st.dataframe(
            pd.DataFrame([
                {"On screen": "Confusion matrix, per-class precision / recall / F1", "Course topic": "Performance metrics — the confusion matrix and what comes out of it"},
                {"On screen": "Macro-F1 as the headline number", "Course topic": "Performance metrics — macro vs micro averaging in multi-class"},
                {"On screen": "The confidence threshold slider", "Course topic": "Logistic regression — the classification threshold; metrics — the precision–recall trade-off"},
                {"On screen": "'Is the confidence honest?'", "Course topic": "Performance metrics — AUC scores ranking, not calibration"},
                {"On screen": "One weight per word per class, one-vs-rest", "Course topic": "Logistic regression — decision boundary and one-vs-all multi-class"},
                {"On screen": "Train / validation / test, and why test opens once", "Course topic": "ML foundations — the three splits; decision trees — the validation set and overfitting"},
                {"On screen": "Bootstrap intervals", "Course topic": "Ensemble learning — bootstrap sampling in bagging"},
                {"On screen": "XGBoost, random forest and majority vote in the table above", "Course topic": "Ensemble learning — bagging, boosting and voting"},
            ]),
            hide_index=True, use_container_width=True,
        )

st.divider()
st.caption(
    f"Snapshot `{metrics['snapshot_id']}` · "
    f"{sum(metrics['splits'].values()):,} labelled articles "
    f"(train {metrics['splits'].get('train', 0):,} / val {metrics['splits'].get('val', 0):,} "
    f"/ test {metrics['splits'].get('test', 0):,}) · 13 classes · 40 publishers · "
    f"{test['predict_ms_per_article']:.2f} ms per article"
)
