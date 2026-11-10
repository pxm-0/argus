"""`argus op` and `argus workload deploy|start|stop|restart`: operator API flows.

The bootstrap token is read only through getpass on /dev/tty. Preview and
approval stay separate steps: the operator confirms the previewed digest (typed
workload ID on a TTY, or --yes-digest) before anything is created.
The server binds approval to the originating session, so `create` carries the
whole preview -> confirm -> step-up -> create -> approve -> watch flow in one
process. There are no standalone approve/cancel verbs: the server refuses both
from any other session.
"""

from __future__ import annotations

import getpass
import re
import time
from pathlib import Path
from typing import Any, Callable

from argus_api_client import TERMINAL_STATES, ApiClient, ApiResponse, ApiUnavailable, is_loopback_http

SHORTCUTS = ("deploy", "start", "stop", "restart")
TYPE_PATTERN = re.compile(r"^[a-z][a-z.-]{0,63}$")
STATE_EXIT = {"succeeded": 0, "denied": 3, "expired": 3, "failed": 4, "rolled-back": 4, "indeterminate": 5}
POLL_SECONDS = 2.0
POLL_FAILURES = 3
DEFAULT_TIMEOUT = 600.0
STEP_UP_REQUIRED = "step-up reauthentication required"


class _Tty:
    """Separate read and write handles: a terminal is not seekable, so text-mode "r+" fails."""

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    def write(self, text: str) -> None:
        self._writer.write(text)
        self._writer.flush()

    def read_line(self, prompt: str) -> str:
        self.write(prompt)
        return self._reader.readline().rstrip("\n")

    def read_secret(self, prompt: str) -> str:
        return getpass.getpass(prompt, stream=self._writer)

    def close(self) -> None:
        self._reader.close()
        self._writer.close()


def open_tty(path: str = "/dev/tty") -> _Tty | None:
    try:
        reader = open(path, "r")  # noqa: SIM115 - closed by the flow
    except OSError:
        return None
    try:
        writer = open(path, "w")  # noqa: SIM115 - closed by the flow
    except OSError:
        reader.close()
        return None
    return _Tty(reader, writer)


class _Stop(Exception):
    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("flow stopped")
        self.result = result


def _clean(value: Any, limit: int = 200) -> str:
    return "".join(c for c in str(value) if c.isprintable())[:limit]


def _bare(digest: Any) -> str:
    return str(digest).removeprefix("sha256:")


class _Flow:
    def __init__(self, cli: Any, repo: Path, args: Any) -> None:
        self.cli, self.repo, self.args = cli, repo, args
        self.client: ApiClient | None = None
        self.tty: _Tty | None = None

    def stop(self, code: str, message: str, next_action: str, exit_code: int, **kwargs: Any) -> _Stop:
        return _Stop(self.cli._error(code, message, next_action, exit_code=exit_code, authority="operator-api", **kwargs))

    def call(self, stage: str, send: Callable[[], ApiResponse], ok: tuple[int, ...] = (200, 201, 202), *, indeterminate: bool = False) -> dict[str, Any]:
        try:
            response = send()
        except ApiUnavailable as exc:
            code = self.cli.EXIT_INDETERMINATE if indeterminate else self.cli.EXIT_UNAVAILABLE
            raise self.stop(f"op-{stage}-unavailable", _clean(exc), "Check tailnet connectivity, then run argus op show on any created operation.", code) from None
        if response.status in ok:
            return response.body
        server = _clean(response.body.get("error", "")) if isinstance(response.body.get("error", ""), str) else ""
        transient = response.status >= 500
        code = (self.cli.EXIT_INDETERMINATE if indeterminate else self.cli.EXIT_UNAVAILABLE) if transient else self.cli.EXIT_REFUSAL
        raise self.stop(f"op-{stage}-refused", f"The {stage} step was refused (HTTP {response.status}){': ' + server if server else ''}.", "Resolve the named condition and retry from a fresh preview.", code, data={"httpStatus": response.status, "stage": stage})

    def secret(self, purpose: str) -> str:
        assert self.tty is not None
        token = self.tty.read_secret(f"Argus bootstrap token ({purpose}): ")
        if not token:
            raise self.stop("op-token-empty", "No bootstrap token was entered.", "Retry and enter the token at the prompt.", self.cli.EXIT_INVOCATION)
        return token

    def authenticate(self, stage: str, send: Callable[[ApiClient, str], ApiResponse]) -> None:
        assert self.client is not None
        token = self.secret(stage)
        try:
            if send(self.client, token).status not in (200, 201):
                raise self.stop(f"op-{stage}-rejected", f"The {stage} credential was rejected.", "Verify the bootstrap token and tailnet identity, then retry.", self.cli.EXIT_REFUSAL)
        except ApiUnavailable as exc:
            raise self.stop(f"op-{stage}-unavailable", _clean(exc), "Check tailnet connectivity and retry.", self.cli.EXIT_UNAVAILABLE) from None
        finally:
            token = ""  # drop the only reference we hold

    def connect(self) -> None:
        self.tty = open_tty()
        if self.tty is None:
            raise self.stop("op-tty-required", "A terminal is required: the bootstrap token is read only from /dev/tty.", "Run from an interactive terminal.", self.cli.EXIT_INVOCATION)
        url = self.args.base_url
        if not url:
            routes = self.cli.dashboard_url(self.repo)
            if not routes["ok"]:
                raise _Stop(routes)
            url = routes["data"]["url"]
        if self.args.base_url and not (url.startswith("https://") and self.cli.TAILSCALE_HTTPS_URL.fullmatch(url) or is_loopback_http(url)):
            raise self.stop("op-base-url-invalid", "--base-url must be the tailnet https URL (*.ts.net) or loopback http.", "Pass the URL printed by argus dashboard url.", self.cli.EXIT_INVOCATION)
        try:
            self.client = ApiClient(url)
        except ValueError as exc:
            raise self.stop("op-base-url-invalid", _clean(exc), "Pass the URL printed by argus dashboard url.", self.cli.EXIT_INVOCATION) from None
        self.authenticate("exchange", lambda client, token: client.exchange(token))

    def preview(self) -> dict[str, Any]:
        assert self.client is not None
        args = self.args
        parameters = summary_parameters(args)
        body = self.call("preview", lambda: self.client.preview(args.workload_id, args.operation_type, parameters))
        summary = {
            "workloadId": body.get("workloadId"),
            "operationType": body.get("operationType"),
            "previewDigest": body.get("previewDigest"),
            "expectedRevision": body.get("expectedRevision"),
            "policyVersion": body.get("policyVersion"),
            "targetRevision": parameters.get("targetRevision"),
            "effects": body.get("expectedBlastRadius"),
            "rollback": body.get("rollbackBehavior"),
            "confirmationPhrase": body.get("confirmationPhrase"),
            "allowed": body.get("allowed") is True,
        }
        if not summary["allowed"]:
            raise self.stop("op-policy-denied", f"Policy denies this operation: {_clean(body.get('reason', 'unspecified'))}", "Inspect argus workload show and fix the named precondition.", self.cli.EXIT_REFUSAL, data=summary)
        return summary

    def show_preview(self, summary: dict[str, Any]) -> None:
        assert self.tty is not None
        self.tty.write(
            f"PREVIEW {summary['operationType']} {summary['workloadId']}\n"
            f"  digest   {_clean(summary['previewDigest'])}\n  revision {_clean(summary['expectedRevision'])}"
            f"  target {_clean(summary['targetRevision'] or '-')}\n  effects  {_clean(summary['effects'])}\n"
        )

    def confirm(self, summary: dict[str, Any]) -> None:
        assert self.tty is not None
        self.show_preview(summary)
        if self.args.yes_digest:
            if _bare(self.args.yes_digest) != _bare(summary["previewDigest"]):
                raise self.stop("op-digest-mismatch", "--yes-digest does not match the previewed digest.", "Re-run argus op preview and pass the digest it prints.", self.cli.EXIT_REFUSAL)
            return
        if self.tty.read_line(f"Type the workload ID ({summary['workloadId']}) to confirm: ").strip() != summary["workloadId"]:
            raise self.stop("op-confirmation-mismatch", "The typed workload ID did not match.", "Nothing was created; rerun to try again.", self.cli.EXIT_REFUSAL)

    def approve(self, operation_id: str, confirmation: str) -> None:
        assert self.client is not None
        for attempt in (1, 2):
            response = self._approve_once(operation_id, confirmation)
            if response.status == 403 and response.body.get("error") == STEP_UP_REQUIRED and attempt == 1:
                self.authenticate("step-up", lambda client, token: client.step_up(token))
                continue
            self.call("approve", lambda: response, indeterminate=True)
            return

    def _approve_once(self, operation_id: str, confirmation: str) -> ApiResponse:
        assert self.client is not None
        try:
            return self.client.approve(operation_id, confirmation)
        except ApiUnavailable as exc:
            raise self.stop("op-approve-unavailable", _clean(exc), f"Run argus op show {operation_id} before retrying.", self.cli.EXIT_INDETERMINATE) from None

    def watch(self, operation_id: str) -> dict[str, Any]:
        assert self.client is not None and self.tty is not None
        deadline = time.monotonic() + self.args.timeout
        last, failures = "", 0
        while True:
            try:
                response = self.client.operation(operation_id)
            except ApiUnavailable:
                response = ApiResponse(599, {})
            if response.status == 200:
                failures = 0
                state = str(response.body.get("state", ""))
                if state != last:
                    self.tty.write(f"STATE {state}\n")
                    last = state
                if state in TERMINAL_STATES:
                    return response.body
            else:
                failures += 1
            if failures >= POLL_FAILURES or time.monotonic() >= deadline:
                raise self.stop("op-watch-lost", "The operation outcome could not be observed and is indeterminate.", f"Run argus op show {operation_id}.", self.cli.EXIT_INDETERMINATE)
            time.sleep(POLL_SECONDS)

    def outcome(self, command: str, operation: dict[str, Any]) -> dict[str, Any]:
        state = str(operation.get("state", ""))
        operation_id = _clean(operation.get("operation_id", ""))
        data = {"operationId": operation_id, "state": state, "operationType": operation.get("operation_type"), "workloadId": operation.get("workload_id")}
        code = STATE_EXIT.get(state, self.cli.EXIT_INDETERMINATE)
        if code == 0:
            return self.cli._success(command, **data)
        summary = _clean(operation.get("redacted_summary", "")) or "no summary"
        return self.cli._error(f"operation-{state or 'unknown'}", f"Operation {operation_id} ended {state or 'in an unknown state'}: {summary}", f"Run argus op show {operation_id}.", exit_code=code, authority="operator-api", data={"command": command, **data})

    def operation_summary(self, operation_id: str) -> dict[str, Any]:
        assert self.client is not None
        return self.call("show", lambda: self.client.operation(operation_id))

    def run(self, verb: str) -> dict[str, Any]:
        args = self.args
        self.connect()
        assert self.client is not None
        if verb == "preview":
            summary = self.preview()
            self.show_preview(summary)
            return self.cli._success("op.preview", **summary)
        if verb == "create":
            summary = self.preview()
            self.confirm(summary)
            # Step-up precedes create so the 60 s preview window is not spent typing.
            self.authenticate("step-up", lambda client, token: client.step_up(token))
            created = self.call("create", lambda: self.client.create(args.workload_id, args.operation_type, summary_parameters(args), summary))
            operation_id = str(created.get("operation_id", ""))
            self.approve(operation_id, str(summary["confirmationPhrase"]))
            return self.outcome("op.create", self.watch(operation_id))
        if verb == "show":
            return self.outcome_show(self.operation_summary(args.operation_id))
        return self.outcome("op.watch", self.watch(args.operation_id))

    def outcome_show(self, operation: dict[str, Any]) -> dict[str, Any]:
        keys = ("operation_id", "workload_id", "operation_type", "state", "error_class", "redacted_summary", "created_at", "approved_at", "finished_at")
        return self.cli._success("op.show", operation={key: operation.get(key) for key in keys})


def summary_parameters(args: Any) -> dict[str, Any]:
    revision = getattr(args, "revision", "")
    return {"targetRevision": revision} if revision else {}


def execute(args: Any, repo: Path, cli: Any) -> dict[str, Any]:
    verb = getattr(args, "op_command", None)
    if verb is None:
        verb = "create"
        args.operation_type = f"workload.{args.workload_command}"
    elif verb in {"preview", "create"}:
        args.operation_type = args.operation_type if "." in args.operation_type else f"workload.{args.operation_type}"
    ids_valid = (
        cli.validate_id(getattr(args, "workload_id", "a"))
        and cli.validate_id(getattr(args, "operation_id", "00000000-0000-0000-0000-000000000000"), operation=True)
        and TYPE_PATTERN.fullmatch(getattr(args, "operation_type", "workload.x")) is not None
    )
    if not ids_valid:
        return cli._error("op-argument-invalid", "A workload ID, operation ID, or operation type is invalid.", "Run argus workload list and use exact IDs.", exit_code=cli.EXIT_INVOCATION)
    flow = _Flow(cli, repo, args)
    try:
        return flow.run(verb)
    except _Stop as stop:
        return stop.result
    finally:
        if flow.tty is not None:
            flow.tty.close()


def register(commands: Any, workload_sub: Any, leaf: Callable[..., Any], description: Callable[..., str]) -> None:
    def contract(purpose: str, side_effects: str, example: str) -> str:
        return description(
            purpose,
            "api-session: tailnet identity, operator session, and bootstrap-token step-up",
            "reachable private dashboard API, an interactive terminal, and the bootstrap token typed at the prompt",
            side_effects,
            "operation ID, state, and exit class 0/3/4/5",
            example,
            "run argus op show <operation-id>; stop on a refusal rather than retrying blindly",
        )

    def common(item: Any, *, target: bool, confirm: bool, timeout: bool) -> None:
        item.add_argument("--base-url", default="", help="override the URL from argus dashboard url")
        if confirm:
            item.add_argument("--yes-digest", default="", help="non-interactive confirmation: the previewed digest")
        if timeout:
            item.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait for a terminal state")
        if target:
            item.add_argument("--revision", default="", help="target revision, e.g. sha256:...")

    op = commands.add_parser("op", help="preview, create and watch operations through the API")
    sub = op.add_subparsers(dest="op_command", required=True, parser_class=type(op))
    for verb, effects in (("preview", "none"), ("create", "creates and approves one audited operation after confirmation")):
        item = leaf(sub, verb, help_text=f"{verb} a typed workload operation", contract=contract(f"{verb.title()} a typed workload operation.", effects, f"argus op {verb} nodens workload.deploy --revision sha256:abc"))
        item.add_argument("workload_id")
        item.add_argument("operation_type", help="e.g. workload.deploy (or the short form deploy)")
        common(item, target=True, confirm=verb == "create", timeout=verb == "create")
    for verb, effects, confirm, timeout in (("show", "none", False, False), ("watch", "none", False, True)):
        item = leaf(sub, verb, help_text=f"{verb} an existing operation", contract=contract(f"{verb.title()} an existing operation.", effects, f"argus op {verb} 00000000-0000-0000-0000-000000000000"))
        item.add_argument("operation_id")
        common(item, target=False, confirm=confirm, timeout=timeout)
    for verb in SHORTCUTS:
        item = leaf(workload_sub, verb, help_text=f"{verb} a workload through the operation API", contract=contract(f"{verb.title()} one workload: preview, confirm, step-up, approve, watch.", "creates and approves one audited operation after confirmation", f"argus workload {verb} nodens" + (" --revision sha256:abc" if verb == "deploy" else "")))
        item.add_argument("workload_id")
        common(item, target=verb == "deploy", confirm=True, timeout=True)
