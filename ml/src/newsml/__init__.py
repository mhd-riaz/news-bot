"""Legacy classifier study and shared offline preparation utilities.

Commands read the corpus and write local artifacts, never MongoDB. Newer tooling
reuses this package's cleaning, annotation and near-duplicate utilities.
"""

from .config import CLEANING_VERSION, SEED

__all__ = ["CLEANING_VERSION", "SEED"]
