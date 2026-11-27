"""Read-only, on-demand cosine retrieval; never allocate an article-by-article matrix."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from scipy import sparse
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from .data import digest, documents, read_json

METHODS = ("tfidf", "svd", "neural")
WINDOWS = ("", "fresh", "yesterday", "archive")
FRESH_DAYS = 30  # C2: verified date and 0 <= age <= 30 days
EDITION_TIMEZONE = ZoneInfo("Asia/Kolkata")  # C9 default
EDITION_READY_HOUR = 6  # C9: the edition for day D opens at D+1 06:00 local time
DAY_SECONDS = 86_400.0


class UnknownArticle(ValueError):
    pass


def _timestamp(value: str | None) -> float:
    if not value:
        return float("nan")
    moment = datetime.fromisoformat(value)
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def edition_day(now: datetime) -> date:
    """The latest available daily edition: yesterday, or the day before until 06:00 local."""
    local = now.astimezone(EDITION_TIMEZONE)
    return local.date() - timedelta(days=2 if local.hour < EDITION_READY_HOUR else 1)


class Index:
    def __init__(self, directory: Path, *, clock: Callable[[], datetime] | None = None):
        self.clock = clock or (lambda: datetime.now(UTC))
        self.manifest = read_json(directory / "manifest.json")
        self.training = read_json(directory / "training.json")
        for name, expected in self.training["artifacts"].items():
            if digest(directory / name) != expected:
                raise ValueError(f"artifact digest mismatch: {name}")
        self.rows = documents(directory)
        self.positions = {row["id"]: i for i, row in enumerate(self.rows)}
        self.groups = read_json(directory / "groups.json")
        self.topics = read_json(directory / "topics.json")
        self.assignments = np.load(directory / "assignments.npy", allow_pickle=False)
        self.matrices = {
            "tfidf": sparse.load_npz(directory / "tfidf.npz").tocsr(),
            "svd": np.load(directory / "svd.npy", mmap_mode="r", allow_pickle=False),
            "neural": np.load(directory / "neural.npy", mmap_mode="r", allow_pickle=False),
        }
        self.has_features = np.diff(self.matrices["tfidf"].indptr) > 0
        n = len(self.rows)
        if len(self.groups) != n or len(self.assignments) != n or any(
            matrix.shape[0] != n for matrix in self.matrices.values()
        ):
            raise ValueError("article IDs, groups and representations are not aligned")
        for matrix in self.matrices.values():
            values = matrix.data if sparse.issparse(matrix) else matrix
            if not np.isfinite(values).all():
                raise ValueError("article representations contain invalid values")
        self.published = np.array([_timestamp(row.get("published_at")) for row in self.rows])
        # Archives frozen before date provenance existed fall back to the same C1 legacy rule.
        self.verified = np.array([
            bool(row.get("date_verified", row.get("date_kind") == "Stored publication date"))
            for row in self.rows
        ]) & np.isfinite(self.published)
        self.domains = [frozenset(row.get("domains") or ()) for row in self.rows]

    def windows(self, now: datetime) -> dict[str, np.ndarray]:
        age = now.timestamp() - self.published
        with np.errstate(invalid="ignore"):
            fresh = self.verified & (age >= 0) & (age <= FRESH_DAYS * DAY_SECONDS)
            start = datetime.combine(edition_day(now), time(), EDITION_TIMEZONE).timestamp()
            yesterday = self.verified & (self.published >= start) & (self.published < start + DAY_SECONDS)
        return {"fresh": fresh, "yesterday": yesterday, "archive": ~fresh}

    def metadata(self) -> dict[str, Any]:
        now = self.clock()
        windows = self.windows(now)
        domains = Counter(tag for tags in self.domains for tag in tags)
        return {
            "snapshot_id": self.manifest["snapshot_id"], "articles": len(self.rows),
            "publication_range": self.manifest["publication_range"],
            "collected_before": self.manifest["collected_before"],
            "methods": list(METHODS), "topics": self.topics,
            "profile_note": "Based on article content and your selections, not historical users.",
            "date_note": self.manifest["date_note"],
            "windows": {name: int(mask.sum()) for name, mask in windows.items()},
            "fresh_days": FRESH_DAYS, "edition_date": edition_day(now).isoformat(),
            "edition_timezone": EDITION_TIMEZONE.key, "domains": dict(sorted(domains.items())),
        }

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("body must be an object")
        unknown = set(payload) - {
            "seed_id", "liked", "disliked", "viewed", "topic", "method", "limit", "window", "domains",
        }
        if unknown:
            raise ValueError("unknown recommendation fields")
        request = {
            "seed_id": "", "liked": [], "disliked": [], "viewed": [],
            "topic": "", "method": "neural", "limit": 12, "window": "", "domains": [], **payload,
        }
        if request["method"] not in METHODS:
            raise ValueError("method must be tfidf, svd or neural")
        if not isinstance(request["window"], str) or request["window"] not in WINDOWS:
            raise ValueError("window must be fresh, yesterday or archive")
        domains = request["domains"]
        if not isinstance(domains, list) or len(domains) > 8 or any(
            not isinstance(value, str) or not value or len(value) > 64 for value in domains
        ):
            raise ValueError("domains must contain at most 8 short tags")
        request["domains"] = sorted(set(domains))
        if type(request["limit"]) is not int or not 1 <= request["limit"] <= 30:
            raise ValueError("limit must be an integer between 1 and 30")
        if not isinstance(request["seed_id"], str) or not isinstance(request["topic"], str):
            raise ValueError("seed_id and topic must be strings")
        if request["topic"] and request["topic"] not in {topic["id"] for topic in self.topics}:
            raise ValueError("unknown topic")
        for name, maximum in (("liked", 50), ("disliked", 50), ("viewed", 2000)):
            values = request[name]
            if not isinstance(values, list) or len(values) > maximum or any(
                not isinstance(value, str) or not value or len(value) > 64 for value in values
            ):
                raise ValueError(f"{name} must contain at most {maximum} article IDs")
            request[name] = list(dict.fromkeys(values))
        if set(request["liked"]) & set(request["disliked"]):
            raise ValueError("an article cannot be both liked and disliked")
        required = request["liked"] + request["disliked"] + (
            [request["seed_id"]] if request["seed_id"] else []
        )
        if any(article_id not in self.positions for article_id in required):
            raise UnknownArticle("an interest or seed article is outside this indexed archive; reset interests")
        return request

    def recommend(self, payload: Any) -> dict[str, Any]:
        request = self.validate(payload)
        now = self.clock()
        windows = self.windows(now)
        window = request["window"]
        matrix = self.matrices[request["method"]]
        positives = [request["seed_id"]] if request["seed_id"] else request["liked"]
        blocked_ids = set(request["viewed"] + request["disliked"] + request["liked"] + positives)
        blocked_groups = {self.groups[self.positions[value]] for value in blocked_ids if value in self.positions}
        reason = "Explore this archive"
        with threadpool_limits(limits=2):
            if positives:
                positions = [self.positions[value] for value in positives]
                if not self.has_features[positions].any():
                    raise ValueError("these articles have no usable features; choose another interest")
                positions = [position for position in positions if self.has_features[position]]
                profile = np.asarray(matrix[positions].mean(axis=0)).reshape(1, -1)
                if not np.linalg.norm(profile):
                    raise ValueError("these articles have no usable features; choose another interest")
                profile = normalize(profile)[0]
                scores = np.asarray(matrix @ profile).ravel()
                reason = "Related to this article" if request["seed_id"] else "Based on your selections"
            elif window in ("fresh", "yesterday"):
                # With no profile yet, a news window reads newest first.
                with np.errstate(invalid="ignore"):
                    age_days = (now.timestamp() - self.published) / DAY_SECONDS
                    scores = np.nan_to_num(np.exp(-age_days / 7), nan=0.0).astype(np.float32)
                reason = "Published yesterday" if window == "yesterday" else "Newest verified news"
            else:
                scores = np.zeros(len(self.rows), dtype=np.float32)
                for topic in self.topics:
                    for rank, article_id in enumerate(topic["representatives"]):
                        scores[self.positions[article_id]] = 1.0 - rank / 20
            if request["disliked"]:
                positions = [self.positions[value] for value in request["disliked"]]
                negative = normalize(np.asarray(matrix[positions].mean(axis=0)).reshape(1, -1))[0]
                scores -= 0.2 * np.asarray(matrix @ negative).ravel()
        allowed = self.has_features.copy()
        if window:
            allowed &= windows[window]
        if request["domains"]:
            wanted = set(request["domains"])
            allowed &= np.fromiter((bool(tags & wanted) for tags in self.domains), bool, len(self.rows))
        if request["topic"]:
            allowed &= self.assignments == int(request["topic"])
            if not positives:
                reason = "Explore this content group"
        for i, group in enumerate(self.groups):
            if group in blocked_groups:
                allowed[i] = False
        ranking = np.argsort(-scores, kind="stable")
        publishers: Counter[str] = Counter()
        chosen = []
        chosen_groups: set[str] = set()
        # Relax only publisher diversity, never duplicate or history exclusion.
        for cap in (max(2, request["limit"] // 3), request["limit"]):
            for position in ranking:
                i = int(position)
                row, group = self.rows[i], self.groups[i]
                if not allowed[i] or group in chosen_groups or publishers[row["publisher"]] >= cap:
                    continue
                # A daily edition ranks every eligible story; other views keep only related ones.
                if positives and scores[i] <= 0 and window != "yesterday":
                    continue
                chosen.append({
                    "id": row["id"], "score": round(float(scores[i]), 5),
                    "reason": reason, "text": row["display_text"],
                    "text_kind": row["display_kind"], "input_kind": row["text_kind"],
                    "topic": str(int(self.assignments[i])),
                    "published_at": row.get("published_at"),
                    "date_verified": bool(self.verified[i]), "fresh": bool(windows["fresh"][i]),
                })
                chosen_groups.add(group)
                publishers[row["publisher"]] += 1
                if len(chosen) == request["limit"]:
                    break
            if len(chosen) == request["limit"]:
                break
        return {
            "items": chosen, "method": request["method"], "snapshot_id": self.manifest["snapshot_id"],
            "exhausted": len(chosen) < request["limit"],
            "ignored_viewed_ids": sum(value not in self.positions for value in request["viewed"]),
            "window": window,
            **({"edition_date": edition_day(now).isoformat()} if window == "yesterday" else {}),
        }
