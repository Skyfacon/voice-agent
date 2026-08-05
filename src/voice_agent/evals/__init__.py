"""Offline evaluation utilities.

Evaluation inputs are deliberately kept outside the runtime control plane.  In
particular, gold labels must never be passed to a model adapter or appended to a
session event journal.
"""
