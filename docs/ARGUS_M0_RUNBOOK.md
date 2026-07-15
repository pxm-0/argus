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
