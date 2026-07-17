# Argus M0 Legacy Quarantine Runbook

This runbook implements the read-only evidence and quarantine portion of
[Argus M0](https://github.com/pxm-0/oreo-cloud/issues/131). It does not authorize
server mutations. Remediation requires a reviewed command, rollback command,
health check, and private before/after evidence for each finding.

## Safety boundary

- Run discovery on `oreochiserver`; laptop output is not server evidence.
- Do not add new workloads to the rootful legacy runtime.
- Do not promote a workload out of `legacy-unclassified` during M0.
- Do not print environment variables, credentials, raw firewall rules, raw
  mount sources, container configuration, or private addresses in PRs.
- Keep generated evidence under `runtime/argus/`. The directory is ignored by
  Git and the inventory file is written with mode `0600`.

## Capture the baseline

From the repository root on `oreochiserver`:

```bash
sudo scripts/argus-legacy-inventory
```

The command is read-only. It collects normalized evidence for:

- listening TCP and UDP ports, recording address scope without the address;
- running containers and Compose identities;
- Docker networks and volumes;
- bind, volume, and tmpfs mounts, replacing host sources with correlation
  hashes;
- published container ports and wildcard exposure findings;
- configured local, tailnet, and Cloudflare route presence;
- nftables or iptables enforcement metadata without copying the ruleset.

The command writes a complete private bundle only. Use `--summary-json` when a
machine-readable, public-safe summary is needed; the former `--json` full-output
mode is intentionally unavailable.

Exit code `0` means all required collectors ran. Exit code `2` means the file
was written but at least one evidence source was unavailable. Treat an evidence
gap as a blocker, never as a clean result.

The private evidence is written to:

```text
runtime/argus/legacy-inventory.json
```

## Review the quarantine baseline

Run:

```bash
python3 -m json.tool config/argus/legacy-classification.json >/dev/null
scripts/oreo-doctor
python3 -m unittest discover -s tests -p 'test_*.py'
```

Every ID in `config/workloads.json` must have exactly this starting state:

```text
realm: unclassified
zone: legacy
stage: none
trustDomain: legacy-rootful
status: legacy-unclassified
admission: denied
```

`config/policy.json` must keep `allowNewLegacyRootfulAdmission` false. The
baseline records existing resources; it does not permit new admission.
`scripts/oreo-workload-add` enforces the rule and fails closed while M0 is
active. Discovery remains read-only through `scripts/oreo-workload-discover`.

## Remediation evidence contract

For each blocking finding, keep the following in private server evidence:

1. finding identifier and affected resource correlation reference;
2. intended containment result;
3. exact reviewed change command;
4. exact rollback command and rollback trigger;
5. pre-change health result;
6. post-change reachability, mount, and health result;
7. rollback rehearsal result where the change is stateful or disruptive;
8. operator, timestamp, source revision, and inventory digest.

Never paste raw inventory files into this public repository. Summarize only the
number and category of findings, the pass/fail result, and a redacted evidence
digest.

## Plan, evidence, and isolation checks

After a complete privileged inventory, create typed remediation records without
embedding shell commands in a plan file:

```bash
sudo scripts/argus-m0-remediation-plan
sudo scripts/argus-m0-evidence --finding <finding-id> --phase pre
```

Apply only a separately reviewed, per-finding server change. Capture a fresh
inventory, health result, and rollback outcome, then record `post` or `rollback`
evidence with the same finding ID. The evidence command refuses a remediation
plan whose inventory digest no longer matches; `post` evidence also requires
the matching typed action to be marked `approved` in the private plan.

For the reviewed Docker forwarded-ingress containment control, require both
IPv4 and IPv6 Docker forwarding chains and install the boot-time unit together:

```bash
sudo scripts/argus-m0-docker-lockdown --install-systemd --acknowledge-workload-lockdown
sudo systemctl is-enabled argus-m0-docker-lockdown.service
sudo iptables -C DOCKER-USER -j ARGUS_M0_DOCKER_LOCKDOWN
sudo ip6tables -C DOCKER-USER -j ARGUS_M0_DOCKER_LOCKDOWN
```

The control does not modify the host `INPUT` chain, so it does not alter remote
SSH. Its explicit rollback is:

```bash
sudo scripts/argus-m0-docker-lockdown --rollback --confirm-workload-unlock
```

After a fresh inventory and remediation plan, record the verified containment
for Docker-published wildcard findings only. Non-Docker listeners remain
separate private review records; this command never approves them.

```bash
sudo python3 scripts/argus-m0-docker-lockdown-evidence --acknowledge-reviewed-lockdown
```

Resolve the remaining non-Docker wildcard listeners to process classes without
printing raw sockets, addresses, or process IDs. The review falls back to
root-readable socket inode ownership when `ss` has no process name:

```bash
sudo python3 scripts/argus-m0-host-listener-review
```

When that review contains exactly one `sshd` and one `tailscaled` card, the
operator can preserve remote SSH and tailnet transport with an explicit private
exception. The command refuses any other listener set or an enabled Funnel:

```bash
sudo python3 scripts/argus-m0-host-ingress-approval \
  --acknowledge-remote-ssh \
  --acknowledge-tailnet-transport
```

For namespace isolation checks, an operator creates the private, mode-`0600`
`runtime/argus/probe-targets.json` with target IDs, hosts, and ports. Then run:

```bash
sudo scripts/argus-m0-isolation-check
```

The check enters existing container network namespaces only; it never creates a
container. Its output contains opaque container and target references, not host
addresses.

## M0 completion gate

Keep the implementation PR in draft until privileged server evidence proves:

- no runtime control surface, protected infrastructure service, or operator
  identity material is reachable from workload ingress;
- every broad listener is removed or explicitly approved in private evidence;
- firewall and container-forwarding behavior is verified;
- all legacy resources are inventoried and remain quarantined;
- existing workloads remain healthy or a documented rollback completed.

M0 does not include managed-environment promotion, public exposure, rootless
runtime provisioning, or stateful workload migration.
