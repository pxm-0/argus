#!/usr/bin/env python3
"""Advance approved Argus migration parents from durable child outcomes."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from argus_migrations import MigrationCoordinator
from argus_operations import OperationLedger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one coordination pass.")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0 or args.poll_seconds > 30:
        parser.error("--poll-seconds must be greater than zero and at most 30")
    root = Path(os.environ.get("ARGUS_ROOT", "/srv/argus")).resolve()
    operations_db = Path(
        os.environ.get("ARGUS_OPERATIONS_DB", "/var/lib/argus/control/operations.sqlite3")
    )
    observations_db = Path(
        os.environ.get(
            "ARGUS_OBSERVATIONS_DB", root / "runtime" / "argus" / "observations.sqlite3"
        )
    )
    ledger = OperationLedger(
        operations_db,
        require_existing=True,
        migrate_schema=False,
    )
    coordinator = MigrationCoordinator(root, ledger, observations_db=observations_db)
    if args.once:
        outcome = coordinator.run_once()
        print(
            "MIGRATION_COORDINATOR_PASS "
            f"advanced={outcome['advanced']} pending={outcome['pending']} "
            f"indeterminate={outcome['indeterminate']}"
        )
        return 0
    print("Argus migration coordinator active", flush=True)
    while True:
        coordinator.run_once()
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
