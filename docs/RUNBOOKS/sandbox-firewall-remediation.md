# Sandbox Firewall Remediation

This server-only runbook addresses issue `#270`. It removes wildcard bridge
forwarding without rebuilding a sandbox or restarting a workload. All policy
rendering is deterministic Python; no AI or external service participates in
planning, apply, verification, or rollback.

## Policy contract

- Every configured Compose project and logical network resolves to exactly one
  live bridge during preflight.
- Same-project networks receive exact interface-to-interface rules.
- Cross-project traffic is denied unless a reviewed entry exists in
  `config/sandbox-connectivity.json`.
- An exception is scoped by source, target service/network, direction,
  protocol, port, owner, reason, and optional expiry. Runtime service addresses
  are resolution inputs bound into the plan digest; observations alone never
  grant access.
- Unknown, duplicated, missing, or changed identities refuse plan/apply.
- Hastur's declared inner DNS/TLS rules use Hastur's resolved bridge. No other
  project can pivot through those rules. Live outbound TCP remains blocked by
  the pre-existing host UID guard tracked in `#267`; changing that boundary is
  outside this phase.

## Privilege and side effects

`--plan`, `--probe`, and `--verify` are privileged read-only operations because
they inspect rootless network namespaces. `--apply` changes only the selected
sandbox's persisted and live nftables tables. `--rollback` restores only the
selected root-owned firewall backup. No command restarts Docker, Compose,
Caddy, Tailscale, or workloads or alters public exposure.

## Before mutation

Run from the reviewed PR branch in the clean `/srv/argus` checkout on
`oreochiserver`:

```text
sudo scripts/argus-sandbox-firewall --domain personal-sandbox --plan
sudo scripts/argus-sandbox-firewall --domain work-sandbox --plan
sudo scripts/argus-sandbox-firewall --domain personal-sandbox --probe
sudo scripts/argus-sandbox-firewall --domain work-sandbox --probe
```

Repeat each probe three times. Store raw JSON only under a root-owned mode-0700
directory outside the checkout, such as `/var/lib/argus/acceptance/270/`.
Convert each three-run result with `argus-acceptance-summary`; only its emitted
allowlisted Markdown row belongs in the PR.

The plan includes `planDigest`, `mappingDigest`, `policyDigest`, and
`renderedDigest`. Copy only the selected domain's exact `planDigest` into its
apply command. Do not apply when any baseline own-project check fails.

## Apply

```text
sudo scripts/argus-sandbox-firewall \
  --domain personal-sandbox \
  --apply \
  --plan-digest 'sha256:<exact-plan-digest>' \
  --acknowledge-sandbox-firewall-apply
```

Apply one domain at a time. The command recollects runtime identity and refuses
a stale digest. Before changing `/etc/argus/argus-<domain>.nft`, it creates a
root-owned mode-0600 backup under
`/var/lib/argus/firewall-remediation/<domain>/<UTC timestamp>/`. It validates
the candidate with `nft -c`, applies the complete table transaction, persists
the same bytes atomically, and verifies live/persisted equality plus the bounded
connectivity matrix. A failed apply restores the prior config and live rules.

Repeat for `work-sandbox` only after `personal-sandbox` passes.

## Verify

```text
sudo scripts/argus-sandbox-firewall --domain personal-sandbox --verify
sudo scripts/argus-sandbox-firewall --domain work-sandbox --verify
sudo scripts/smoke-test
```

Verification requires persisted bytes and live rules to equal the deterministic
rendering, no wildcard bridge rule, successful own-project probes, denial of
every directed cross-project probe, and full server smoke with zero failures
and zero warnings.

Repeat both verifiers three times for post-apply evidence. Before issue close,
an operator-approved reboot must be followed by both verifiers and full smoke
to prove persisted/live equality.

## Rollback

Use only the exact backup emitted by the selected domain's apply:

```text
sudo scripts/argus-sandbox-firewall \
  --domain personal-sandbox \
  --rollback /var/lib/argus/firewall-remediation/personal-sandbox/<timestamp>/argus-personal-sandbox.nft \
  --acknowledge-sandbox-firewall-rollback
```

Rollback refuses symlinks, non-root ownership, non-0600 files, and paths outside
the selected domain's backup root. It validates before apply and requires the
persisted digest to match afterward. Run the probe matrix and full smoke again,
then document any blocker without copying raw topology into GitHub.
