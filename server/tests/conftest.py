"""Unit tests use fakes from helpers.py; tests/integration use throwaway `news_it_*` databases and drop them."""

from __future__ import annotations

import pytest


@pytest.fixture
def same_origin() -> dict[str, str]:
    """What a browser sends with a same-origin fetch; state-changing requests need it (C10)."""
    return {"Sec-Fetch-Site": "same-origin"}
