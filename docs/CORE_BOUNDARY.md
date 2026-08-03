# Deterministic Argus Core Boundary

Argus core is deterministic and contains no AI, model SDK, model endpoint, or
advisory import path. `config/core-boundary-policy.json` is the machine-readable
contract. `./scripts/argus-check` audits every Python dependency, declared
network-capable entry point, dynamic loader, forbidden model import/endpoint,
and deterministic replay bundle before it runs the rest of the repository suite.

The supported production and CI runtime is Python 3.14 on Linux and macOS.
Linux-only process, Unix-socket, and identity tests are explicitly skipped on
macOS. Server acceptance still runs as a non-root user on `oreochiserver`; a
macOS result is portability evidence, not server evidence.

Replay bundles contain only immutable fixtures and sanitized digests. Raw
observations stay local under the existing retention and redaction rules. The
stable replay outcomes are:

- `replay-ok`
- `replay-mismatch`
- `replay-bundle-incomplete`
- `replay-version-unsupported`

An unsupported historical transform is not labeled nondeterministic. A boundary
failure emits `core-boundary-violation` and identifies the file and authority
class without printing private observations.

Both `argus-check` and `argus-doctor --json` record the policy and audit
versions, dependency/SBOM digest, endpoint/network-policy digest, and audit
result. Replay evidence additionally records the Argus revision, input summary,
output digests, and sanitized evidence ID.

Any future AI capability is a separate product and trust boundary. It must be
isolated from Argus core, receive only explicitly sanitized read-only snapshots,
hold no mutation capability or shared writable state, and be removable without
changing core policy, evidence, or operation results. It is not authorized by
this policy or by the current remediation program.
