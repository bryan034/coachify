"""Compatibility import for the single authoritative saved-CV repository.

Career consumes the saved-CV API; it does not write a second CV snapshot store.
"""
from app.repositories.cv import CvRepository

__all__ = ['CvRepository']
