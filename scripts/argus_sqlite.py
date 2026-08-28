"""Safe SQLite connection primitives shared by long-lived Argus services.

``sqlite3.Connection`` implements transaction context management, but its
context manager deliberately does not close the descriptor.  That is useful
for callers that intentionally retain a connection, but it is unsafe for the
many short-lived transactions used by the control plane.  This subclass keeps
the standard commit/rollback behavior and closes the descriptor on every
context-manager exit.
"""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Type


class ClosingConnection(sqlite3.Connection):
    """A transaction context manager that cannot leak its SQLite descriptor."""

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
