"""Offline data preparation and modelling for the news collector.

Never deployed. Reads the bronze corpus, never writes to it.
"""

from .config import CLEANING_VERSION, SEED

__all__ = ["CLEANING_VERSION", "SEED"]
