"""Argus test-suite package and execution contract."""

from __future__ import annotations

import os


if hasattr(os, "geteuid") and os.geteuid() == 0:
    raise RuntimeError(
        "Argus tests must run as a non-root user; leave the repository checkout "
        "and runtime fixtures owned by that user, then run ./scripts/argus-check."
    )
