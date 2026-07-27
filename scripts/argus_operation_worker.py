from __future__ import annotations

import argparse
import json
import os
import re
import socket
import stat
import time
from pathlib import Path
from typing import Any

from argus_operations import OperationConflict, OperationLedger


DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_RESPONSE_BYTES = 65_536


class OperationWorker:
    def __init__(
        self,
        ledger: OperationLedger,
        agent_socket_dir: Path,
        *,
        dispatch_timeout_seconds: float = 10,
    ) -> None:
        self.ledger = ledger
        self.agent_socket_dir = agent_socket_dir
        self.dispatch_timeout_seconds = dispatch_timeout_seconds

    def socket_path(self, trust_domain: str) -> Path:
        if not DOMAIN_ID.fullmatch(trust_domain):
            raise ValueError("invalid trust domain")
        return self.agent_socket_dir / f"{trust_domain}.sock"

    def dispatch(self, operation: dict[str, Any]) -> bool:
        operation_id = str(operation["operation_id"])
        socket_path = self.socket_path(str(operation["trust_domain"]))
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.dispatch_timeout_seconds)
                client.connect(str(socket_path))
                client.sendall(
                    (
                        json.dumps(
                            {"operationId": operation_id},
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                )
                response_bytes = client.makefile("rb").readline(MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_RESPONSE_BYTES or not response_bytes.endswith(b"\n"):
                raise RuntimeError("invalid agent acknowledgement")
            response = json.loads(response_bytes)
            if response != {"accepted": True, "ok": True}:
                raise RuntimeError("agent rejected dispatch")
            return True
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            try:
                self.ledger.mark_dispatch_indeterminate(operation_id)
            except OperationConflict:
                # A domain agent may have durably completed after the worker lost
                # its acknowledgement. Never overwrite that terminal outcome.
                pass
            return False

    def agent_available(self, trust_domain: str) -> bool:
        try:
            metadata = self.socket_path(trust_domain).stat()
        except (OSError, ValueError):
            return False
        return stat.S_ISSOCK(metadata.st_mode)

    def run_once(self) -> tuple[int, int, int]:
        recovered = self.ledger.recover_running()
        accepted = 0
        indeterminate = 0
        for queued in self.ledger.list_queued():
            if not self.agent_available(str(queued["trust_domain"])):
                continue
            operation = self.ledger.claim(str(queued["operation_id"]))
            if operation is None:
                continue
            if self.dispatch(operation):
                accepted += 1
            else:
                indeterminate += 1
        return accepted, indeterminate, recovered


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch durable Argus operations.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one recovery/dispatch pass and exit.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=1,
        help="Worker polling interval (default: 1 second).",
    )
    args = parser.parse_args()
    if args.poll_seconds <= 0 or args.poll_seconds > 30:
        parser.error("--poll-seconds must be greater than zero and at most 30")

    root = Path(os.environ.get("ARGUS_ROOT", Path(__file__).resolve().parents[1])).resolve()
    ledger_path = Path(
        os.environ.get(
            "ARGUS_OPERATIONS_DB",
            "/var/lib/argus/control/operations.sqlite3",
        )
    )
    socket_dir = Path(
        os.environ.get(
            "ARGUS_AGENT_SOCKET_DIR",
            root / "runtime" / "argus" / "m5" / "agents",
        )
    )
    ledger = OperationLedger(ledger_path)
    worker = OperationWorker(ledger, socket_dir)

    if args.once:
        accepted, indeterminate, recovered = worker.run_once()
        print(
            "OPERATION_WORKER_PASS "
            f"accepted={accepted} indeterminate={indeterminate} recovered={recovered}"
        )
        return 0

    print("Argus operation worker active")
    while True:
        worker.run_once()
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
