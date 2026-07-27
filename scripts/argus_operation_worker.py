from __future__ import annotations

import argparse
import grp
import os
import pwd
import re
import stat
import time
from pathlib import Path
from typing import Any

from argus_ipc import request as ipc_request
from argus_operations import OperationConflict, OperationLedger


DOMAIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
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
        return self.agent_socket_dir / trust_domain / "agent.sock"

    @staticmethod
    def expected_owner(trust_domain: str) -> str:
        return "oreo" if trust_domain == "legacy-rootful" else f"argus-{trust_domain}"

    def dispatch(self, operation: dict[str, Any]) -> bool:
        operation_id = str(operation["operation_id"])
        socket_path = self.socket_path(str(operation["trust_domain"]))
        try:
            response = ipc_request(
                str(socket_path),
                {
                    "method": "operation.execute",
                    "operationId": operation_id,
                },
                timeout_seconds=self.dispatch_timeout_seconds,
            )
            if response != {"accepted": True, "ok": True}:
                raise RuntimeError("agent rejected dispatch")
            return True
        except (OSError, ValueError, RuntimeError):
            try:
                self.ledger.mark_dispatch_indeterminate(operation_id)
            except OperationConflict:
                # A domain agent may have durably completed after the worker lost
                # its acknowledgement. Never overwrite that terminal outcome.
                pass
            return False

    def agent_available(self, trust_domain: str) -> bool:
        try:
            socket_path = self.socket_path(trust_domain)
            metadata = socket_path.stat()
            expected_uid = pwd.getpwnam(self.expected_owner(trust_domain)).pw_uid
            expected_gid = grp.getgrnam("argus-control").gr_gid
            if (
                not stat.S_ISSOCK(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o660
                or metadata.st_uid != expected_uid
                or metadata.st_gid != expected_gid
            ):
                return False
            response = ipc_request(
                str(socket_path),
                {"method": "agent.status"},
                timeout_seconds=self.dispatch_timeout_seconds,
            )
        except (KeyError, OSError, ValueError, RuntimeError):
            return False
        return response == {
            "ok": True,
            "status": "available",
            "trustDomain": trust_domain,
        }

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
            "/run/argus/domains",
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
