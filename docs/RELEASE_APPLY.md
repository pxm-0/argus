# `argus release apply` (v1 design)

Design for the one-command root release apply, chosen 2026-11-21 from three competing designs (safety-first base). Citations were checked against main at that date.

## Goal
Give the root operator one typed, previewed, idempotent command that does five things:
1. Activates a merged commit as the running code release.
2. Converges the host's unit files, drop-ins, sysusers, sudoers and release overrides to that release.
3. Restarts the daemons in dependency order with a doctor gate after each restart.
4. Runs smoke.
5. Records `{sha, doctor, smoke}` in root-owned evidence.

Rollback is the same command with the previous sha. Today these steps are spread across manual runbook blocks:
- docs/RUNBOOKS/root-owned-release.md:66-110
- docs/RUNBOOKS/sudo-narrowing.md:56-67
- docs/MONITORING.md:87-104
- docs/BACKUP_AND_RESTORE.md:118-123, :156-161, :191-196
- docs/P5_SCHEDULED_SMOKE.md:46-63
- docs/OPERATIONS.md:415-417

## Non-goals
- **No unattended or timer-driven apply.** D022 requires the bundle to be "run directly by the host administrator" (docs/ARGUS_V1_DECISIONS.md:179-183). Automation needs a root-owned mirror or signed commits (docs/RUNBOOKS/sudo-narrowing.md:174-177).
- **No server network calls.** No GitHub API, no gpg, no web-flow key. A new network entry point is denied by default (config/core-boundary-policy.json:66). A signed-commit trust root changes the trust anchor (root-owned-release.md:29-30). Both need their own D-record.
- **No `git fetch` as root.** No `git status` or `git archive` ever (scripts/argus-release-install:22-24, :122-171).
- **Never deletes, enables or disables a unit, and never `rm -r`s a `<unit>.d` dir** (the trap at docs/MONITORING.md:155-156).
- **Never installs units that are absent from the host.** These are reported only: monitoring, backup and P5 timers, `argus-metrics.timer`, `argus-workload-discover.timer`, cloudflared (D027).
- **No automatic rollback.** No schema rollback either: migrations are forward-only (docs/ARGUS_M5_PHASE1_RUNBOOK.md:169-174).
- **No `runtime/audit.log` line.** `audit()` writes `root()/runtime/audit.log` (scripts/argus_common.py:176-188), which is root writing through the oreo-owned symlink (root-owned-release.md:43-48).
- **No `release status` subcommand and no stager hooks.**
- **No signed evidence.** This is a named gap against D022's "signed redacted evidence" (ARGUS_V1_DECISIONS.md:181). See open question 2.

## CLI surface
```
argus release apply --sha <40 lowercase hex> --plan
argus release apply --sha <40 lowercase hex> --confirm <plan-digest>
```
- **Arguments.** Exactly one of `--plan` or `--confirm` is required; a bare `apply` exits 2. `allow_abbrev=False`, no positionals, no `--prefix` or `--root`. The sha regex is the installer's `SHA` (scripts/argus-release-install:45, :78-79). Abbreviated, uppercase and ref names exit 2.
- **Registration.** Add the `apply` leaf in `argus_release.register` (scripts/argus_release.py:365-372).
- **Dispatch.** Add an `apply` branch at the top of `argus_release.dispatch`, before the `else` that falls into `release_import` (scripts/argus_release.py:388-398). The branch is an exec shim:
  1. Refuse with exit 3 if `ARGUS_ROOT` is set. `main` trusts it (scripts/argus_cli.py:1343-1345).
  2. Refuse with exit 3 if `SUDO_USER`, `SUDO_UID` or `SUDO_COMMAND` is set.
  3. Resolve `Path(__file__).resolve().parent / "argus-release-apply"`.
  4. Run `os.execve("/usr/bin/python3", ["/usr/bin/python3", "-I", script, *argv], {"PATH": "/usr/bin:/bin"})`.
  5. The script itself repeats every guard.
- **Direct use.** Running `/opt/argus/current/scripts/argus-release-apply` directly is equivalent.
- **Root only.** It refuses unless euid is 0. `--plan` is root-only as well, because it reads `/etc/sudoers.d` (0440) and the backups.
- **Never in sudoers.** Same rule as the installer (scripts/argus_sudoers.py:97; tests/test_argus_sudoers.py:84-86).
- **Exit classes** (docs/OPERATIONS.md:31-33; scripts/argus_cli.py:1005-1009):

| Code | When |
|---|---|
| 0 | Applied, or already converged, with doctor and smoke ok |
| 2 | Invalid invocation |
| 3 | Refused before any mutation, including a stale confirm digest |
| 4 | A tool or evidence source is unavailable before any mutation (lock held, systemctl, visudo, baseline doctor) |
| 5 | Any failure after the first mutation, including doctor regression, smoke fail or stale smoke. Nothing is retried. The rollback command is printed. |

## Algorithm
Steps 1-7 only read; `--plan` stops after step 7. Steps 8-15 run only with a matching `--confirm`, and they recompute steps 1-7 first.

1. **Guards.**
   - euid is 0.
   - No `SUDO_*` variables. This is defence in depth: the installer's usage line starts with `sudo` (scripts/argus-release-install:4-7, :234-236).
   - Sealed location: `realpath(__file__)` and every ancestor up to `/` are owned by uid 0, with no group or other write. This rejects `/srv/argus/scripts`.
   - `umask 022`.
2. **Lock.** `flock` on `/run/argus-release-apply.lock`, opened `O_CREAT|O_NOFOLLOW` at 0600. If it is held, exit 4.
3. **Load helpers from the script's own sealed dir** with `SourceFileLoader`:
   - `argus-release-install` (pattern at tests/test_argus_release_install.py:19-21) for `require_known_commit`, `git`, `extract_commit`, `git_tree_hash`, `switch_current`, `install_release`, `STAMP`, `SHA`;
   - `argus_sudoers`, which is stdlib-only (scripts/argus_sudoers.py:10-18).
4. **Trust the sha.** All git is local and runs under the installer's `GIT_ENV`/`GIT_BASE` (scripts/argus-release-install:52-73).
   - a. `require_known_commit(/srv/argus, sha, origin/main)`: the commit resolves, is an ancestor of origin/main, re-hashes to the sha, and yields the tree id (:76-92). If the commit is missing, the refusal text is `fetch as oreo first: runuser -u oreo -- git -C /srv/argus fetch origin`. Apply never fetches.
   - b. New check: the sha must be in `rev-list --first-parent origin/main`. Otherwise refuse with `not a merge to main (branch commit?)`. Main uses merge commits (`git log --first-parent`: "Merge pull request #422…"), and `gh pr view --json mergeCommit` returns exactly that sha (root-owned-release.md:29-30).
   - c. `previous` is `/opt/argus/current/ARGUS_RELEASE` (:220). The plan marks a `ROLLBACK` when the sha is an ancestor of `previous`.
5. **Release action.**
   - `install`: `/opt/argus/releases/<sha>` is absent.
   - `noop`: current already resolves to `releases/<sha>`.
   - `switch`: the dir exists and passes `verify_existing`:
     1. Re-extract the commit into a 0700 temp dir under `/var/lib/argus/releases/tmp`, using `extract_commit` plus a `git_tree_hash` match (:122-171, :216-218).
     2. Compare it with the release dir without following symlinks: the same set of paths, bytes and executable bits, with everything owned by 0:0 and no group or other write.
     3. The only allowed differences are `STAMP` (which must equal the sha) and the three state paths, which must be symlinks to exactly `/srv/argus/<path>` (:43-44, :186-192).
     4. Any failure refuses with `release dir tampered`. Apply never repairs or reuses such a dir.
   - **Candidate tree.** For `install` it is the temp extraction; for the other two it is the release dir. Changed in implementation (#428): the candidate's own `scripts/argus_sudoers.py` renders the release overrides, loaded from this hash-verified tree. The previous release's renderer would lag one release behind, and the verified code becomes current moments later anyway. No other candidate code runs before the switch.
6. **Desired /etc state from the candidate.** Scope is files that already exist on the host, plus every rendered drop-in and the sudoers file.

   | Source | Destination | Owner and mode |
   |---|---|---|
   | `systemd/*.service`, `systemd/*.timer` | `/etc/systemd/system/` | root:root 0644 |
   | `systemd/<unit>.d/*.conf` | `/etc/systemd/system/<unit>.d/` | dir 0755, file 0644 |
   | `systemd/sysusers.d/*.conf` | `/etc/sysusers.d/` | 0644 |
   | `render_overrides(candidate, "/opt/argus/current", units_dir=<the desired unit set: installed units overlaid with candidate units>)` (scripts/argus_sudoers.py:287-305) | `10-argus-release.conf` and `20-argus-docker-group.conf` | 0644 |
   | `render_sudoers(...)` (:123) | `/etc/sudoers.d/argus-operator` | root:root 0440 |

   - The override row covers the generated `argus-m5-workload-*` units, which closes root-owned-release.md:108.
   - Sudoers: changed in implementation (#428). The candidate's committed `deploy/sudoers/argus-operator` is installed as-is. Comparing it with the previous release's renderer would refuse every release that changes the renderer. CI already proves the committed file equals its own renderer's output (tests/test_argus_sudoers.py), and `visudo -cf` checks it before any change.
   - `templates/systemd/` is never a source. Its control-api unit is the stale `User=oreo` copy (templates/systemd/argus-control-api.service:7).
   - Drift classes per path:

   | Class | Meaning |
   |---|---|
   | `same` | nothing to do |
   | `update` | content differs; the plan shows a unified diff, capped |
   | `mode-owner` | only mode or owner differs |
   | `create` | drop-ins and sudoers only |
   | `available-not-installed` | in the candidate but not on the host |
   | `managed-orphan` | carries a "Managed by" header but is no longer desired; report only |
   | `unmanaged` | ignored |
   | `refuse` | the target or its parent is a symlink, not root-owned, or group/other writable |

7. **Restart set and plan output.**
   - The set is the daemons in `restart_units` order (scripts/argus_sudoers.py:102-104), filtered to those that are active. It is grouped by the `Requires=` graph:

     | Group | Units |
     |---|---|
     | 1 | `argus-operation-worker`, which systemd cascades to its dependents |
     | 2 | `argus-capability-issuer` |
     | 3 | `argus-control-api`, `argus-migration-coordinator`, `argus-privileged-lifecycle-agent` |
     | 4 | each active `argus-domain-agent@*`, then `argus-domain-agent-legacy-rootful` |
     | 5 | `caddy`, only if a `caddy.service.d` file drifted |

     The graph comes from systemd/argus-capability-issuer.service:3, argus-control-api.service:3, argus-migration-coordinator.service:3, argus-domain-agent@.service:3, argus-domain-agent-legacy-rootful.service:3 and argus-privileged-lifecycle-agent.service:3. This order replaces the four conflicting ones at root-owned-release.md:80-87, emergency-rollback.md:71-75, argus-m5-capability-issuer:562-569 and argus-m5-ledger-worker:498-504.
   - Baseline doctor: run `/opt/argus/current/scripts/argus-doctor --host --json`. Output is `{ok, failures, checks}` (scripts/argus-doctor:569-606). Record the set of failing `check.get("check") or check["message"]`.
   - A dangling `started` row in history (step 9) is shown, and the digest binds it. Confirming the plan acknowledges it, so no extra flag is needed.
   - The plan prints the CI attestation the operator must run on the laptop: `gh pr view <n> --json mergeCommit,statusCheckRollup`.
   - Print the plan and `planDigest`, which is sha256 over the canonical JSON of: sha, previous, action, rollback flag, every drift entry with before/after sha256, the restart groups, baseline failures, the dangling run id, and `/proc/sys/kernel/random/boot_id`.
   - `--plan` exits 0 here.
8. **Confirm.** Recompute steps 1-7. If the digest differs from `--confirm`, exit 3 with `plan changed; re-run --plan`. Write `runs/<runId>/plan.json`.
9. **Intent first** (D014, ARGUS_V1_DECISIONS.md:131-135). Append a `started` row. Everything after this point exits 5 on failure.
10. **Activate.**
    - `install`: run `/opt/argus/current/scripts/argus-release-install --sha <sha>` as a subprocess, so the previously trusted installer runs and not the candidate's. A refusal from it passes through, and exit 5 is recorded.
    - `switch`: call `switch_current(/opt/argus/current, releases/<sha>)` (:195-200).
    - `noop`: do nothing.
11. **Converge /etc.**
    - For each non-`same` entry, copy the old file to `runs/<runId>/backup/<abs path>` (0700 dir). Then write a temp file in the same dir with `O_EXCL|O_NOFOLLOW`, fchown, fchmod, fsync, and `os.replace` it into place.
    - If sysusers changed, run `systemd-sysusers`.
    - Sudoers:
      1. Write `/etc/sudoers.d/.argus-operator.new`. sudo ignores names with a dot.
      2. Run `visudo -cf` on it, rename it into place, then run `visudo -c`.
      3. If that fails, restore the backup, rerun `visudo -c`, and exit 5.
    - Then `systemctl daemon-reload`, only if anything changed or current moved.
    - Correction to the judged input: once `10-argus-release.conf` is installed, `argus-smoke.service` runs from `/opt/argus/current` with `WorkingDirectory` repointed, because `render_override` rewrites every Exec and WorkingDirectory that contains `/srv/argus` (scripts/argus_sudoers.py:267-284; systemd/argus-smoke.service:7,15). The judges' "smoke describes the checkout" holds only when that drop-in is absent. Step 13 checks for it.
12. **Restart and gate.** Take mark `T = CLOCK_MONOTONIC` after the reload. For each unit in group order:
    - Skip it if `ActiveEnterTimestampMonotonic` is greater than `T`. Either it cascaded from an earlier group, or a re-run is resuming.
    - Otherwise run `systemctl restart`, then assert `ActiveState=active` and a start timestamp greater than `T` for the unit and for every unit systemd pulled along with it. This is the restart proof the doctor cannot give, since its ExecStart check reads loaded config (scripts/argus-doctor:426-440).
    - Then run `releases/<sha>/scripts/argus-doctor --host --json` and store it as `doctor-<n>.json`.
    - If any failure is not in the baseline set, stop the loop: write a `finished` row with outcome `indeterminate`, print `argus release apply --sha <previous> --plan`, and exit 5.
    - Timers and oneshots are not restarted; they pick up changes on their next run (root-owned-release.md:91).
13. **Smoke.**
    - Run `systemctl start argus-smoke.service`. It is a oneshot running as oreo, so it blocks until done (systemd/argus-smoke.service:7,16-17).
    - Read `/srv/argus/runtime/smoke/latest.json` with `O_NOFOLLOW`, keeping only the known keys (scripts/argus-smoke-scheduled:121-131).
    - `timestamp` must be later than the smoke start; otherwise smoke counts as not ok, reason `stale`.
    - Store the file's sha256 too. It is oreo-writable data: evidence, not proof.
    - Record `smoke.scope = "release"` if `systemctl show -p ExecStart argus-smoke.service` contains `/opt/argus/current`, else `"checkout"`.
14. **Final doctor.** Run the same doctor command once more.
15. **Finish.** Append the `finished` row and print `applied <sha> (prev <prev>) doctor=ok smoke=ok`. The exit is 0 only when doctor has no new failures and smoke is ok; otherwise 5 plus the rollback line.

**Idempotency and resume.** A re-run with the same sha converges: action `noop`, all files `same`, and restarted units skipped. It still runs doctor and smoke and appends evidence, so re-applying doubles as a verify record. After a crash, re-run `--plan` with the same sha, or with the previous sha to back out. The dangling run is bound into the digest.

## Evidence
- **Location.** `/var/lib/argus/releases/` (root 0755), next to `/var/lib/argus/control` (scripts/argus_common.py:101-104). Not `runtime/`.
  - `history.jsonl` (0644): opened `O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW`, one `write` plus `fsync` per row, never pruned. It does not reuse `append_history`, which prunes after 30 days, rewrites the whole file, and lives in an extensionless script (scripts/argus-smoke-scheduled:37-54).
  - `runs/<runId>/` (0700): `plan.json`, `doctor-<n>.json`, `smoke.json`, `backup/<abs path>`.
- **Row.** A `started` row carries fields through `rollback`. The `finished` row carries everything:
```json
{"runId":"<utc yyyymmddThhmmssZ>-<sha12>","phase":"started|finished","timestamp":"<iso8601Z>",
 "sha":"<40hex>","previousSha":"<40hex|null>","planDigest":"sha256:<hex>","action":"install|switch|noop",
 "rollback":false,"resumesRunId":null,
 "checks":{"source":"operator-attested"},
 "changedFiles":[{"path":"/etc/...","class":"update","before":"sha256:..","after":"sha256:.."}],
 "restarted":[{"unit":"argus-operation-worker.service","pulled":["argus-control-api.service"]}],
 "skipped":["argus-control-api.service"],
 "doctor":{"ok":true,"newFailures":[],"baselineFailures":[]},
 "smoke":{"ok":true,"scope":"release|checkout","timestamp":"..","exitCode":0,"failures":[],"warnings":[],"latestJsonSha256":".."},
 "outcome":"applied|noop|indeterminate","exit":0,"rollbackCommand":"argus release apply --sha <prev> --plan"}
```
  `failures` and `warnings` are capped at 10, the same cap smoke uses (docs/P5_SCHEDULED_SMOKE.md:36).
- Refusals before step 9 write no row. They only print, and they exit 3 or 4.

## Refusal cases
- **Exit 2:**
  - the sha is not 40 lowercase hex;
  - neither or both of `--plan`/`--confirm`;
  - an unknown flag or a positional.
- **Exit 3:**
  - euid is not 0;
  - a `SUDO_*` variable is set;
  - `ARGUS_ROOT` is set (shim);
  - the script path or an ancestor is not sealed root-owned;
  - the commit is missing locally (the message gives the oreo fetch command);
  - the commit is not an ancestor of origin/main, or is not on the first-parent chain;
  - the commit re-hash differs, or a replace ref is in play (installer);
  - the existing release dir fails `verify_existing`;
  - the rendered sudoers is not equal to the committed copy;
  - `visudo -cf` rejects the candidate (pre-mutation dry check in the plan);
  - a target path or its parent is a symlink, not root-owned, or group/other writable;
  - the confirm digest differs;
  - `/opt/argus/current` is not a symlink into `/opt/argus/releases/` (bootstrap: root-owned-release.md:56-64).
- **Exit 4:** the lock is held, or systemctl, visudo or the baseline doctor cannot run.
- **Exit 5 (after mutation):**
  - the installer fails;
  - the post-install `visudo -c` fails (the backup is restored);
  - a unit is not active or not restarted;
  - doctor shows a new failure;
  - smoke fails or is stale.

## Rollback
Rollback is `argus release apply --sha <previousSha> --plan`, then `--confirm`.
- The previous release dir exists, so the action is `switch` after `verify_existing`.
- `/etc` converges to the previous release's rendering, and the restart and gate run in the same group order.
- Files that exist only in the newer release show as `managed-orphan`, `unmanaged` or `available-not-installed`, and nothing is deleted.
- Every overwritten file remains under `runs/<runId>/backup/` for manual restore.
- The plan warns with `ROLLBACK: forward-only schema migrations are not undone` (docs/RUNBOOKS/emergency-rollback.md:35-65; ARGUS_M5_PHASE1_RUNBOOK.md:169-174). The warning is in the digest.

## Files
- **New**
  - `scripts/argus-release-apply`: standalone, shebang `#!/usr/bin/python3 -I`, about 300 lines. Its core is `apply(sha, *, plan_only, confirm, roots, runner, now, euid, environ, owner=(0,0))`.
    - `roots` is a frozen dataclass of `prefix`, `source`, `etc_systemd`, `sysusers_d`, `sudoers_d`, `state_dir`, `lock`, `smoke_latest`.
    - `runner` is the only subprocess seam, covering systemctl, visudo, systemd-sysusers, the installer and the doctor.
  - `tests/test_argus_release_apply.py`.
- **Changed**
  - `scripts/argus_release.py`: the `apply` leaf and the exec branch.
  - `tests/test_argus_sudoers.py`: next to :84-86, assert that the rendered allowlist contains neither `argus-release-apply` nor `release apply`. Also assert that `argus m1 sync --apply --confirm X release apply --sha …` is rejected by the m1 parser with exit 2, because of the sudoers `*` at scripts/argus_sudoers.py:94.
  - `docs/RUNBOOKS/root-owned-release.md`.
- **Reused unchanged**
  - `scripts/argus-release-install`: subprocess plus loaded helpers; `verify_existing` lives in apply, built from its helpers.
  - `scripts/argus_sudoers.py`
  - `scripts/argus-doctor`
  - `systemd/argus-smoke.service`
  - `config/core-boundary-policy.json`: not touched, since there is no network.

## Test plan (CI, no root, no server)
**Fixtures.**
- A real throwaway git repo built with the helpers at tests/test_argus_release_install.py:45-74. It contains a real merge commit, so first-parent can be tested, and a fake `refs/remotes/origin/main` made with update-ref.
- Temp `roots` with `owner=(getuid, getgid)` and injected `euid=0`.
- `FakeRunner`:
  - records argv;
  - models `systemctl show` monotonic timestamps that advance on restart and cascade along the fixture units' `Requires=`;
  - has a visudo pass/fail switch;
  - returns doctor JSON fixtures;
  - writes smoke `latest.json`;
  - for the installer, calls `install_release` in-process.

| # | Case | Steps |
|---|---|---|
| 1 | `--plan` writes nothing: every root hashed before and after (bytes and mtimes); no mutating argv | 1-7 |
| 2 | Digest is stable across runs; one byte changed in /etc gives exit 3 on confirm | 7-8 |
| 3 | Guards: euid, `SUDO_*`, unsealed script dir (g+w temp dir), lock held (4) | 1-2 |
| 4 | Trust: branch-only commit, ancestor but not first-parent, forged object, missing commit message | 4 |
| 5 | Fresh install: the installer is the old current's; drop-ins exist for every unit, including a workload unit in /etc; one daemon-reload before any restart | 10-11 |
| 6 | Tampered existing dir (stamp, g+w, extra file, redirected state symlink) is refused; current is unchanged | 5 |
| 7 | Rollback A to B to A uses `switch`, restores A's files, keeps backups, shows the ROLLBACK warning | 5, 10-11 |
| 8 | Re-apply: all `same`, no restarts, a new row | 12, 15 |
| 9 | Resume after an injected crash after 10, after 11 and after group 1 converges, and the worker is not restarted twice | 9-12 |
| 10 | A `<unit>.d` holding a foreign conf keeps it; a symlinked target is refused; `templates/systemd` is never read; non-installed units are not installed | 6, 11 |
| 11 | Sudoers: render mismatch gives 3; `visudo -cf` fail leaves the file untouched; post-install `visudo -c` fail restores and gives 5 | 6, 11 |
| 12 | Restart order and cascade skip; a new doctor failure after group 2 stops groups 3-4 and gives 5 with an `indeterminate` row; a baseline failure does not stop | 12 |
| 13 | Smoke that is stale, a symlink, non-JSON or failed gives 5; `scope` is `checkout` without the drop-in | 13 |
| 14 | History rows carry `started`/`finished` with the schema keys; no write under `runtime/` | 9, 15 |
| 15 | Static: the source contains no `"status"`, `"archive"` or `"fetch"` git call (as at tests/test_argus_release_install.py:226-227), and no `audit(` | all |
| 16 | Shim: `ARGUS_ROOT` or `SUDO_*` set gives 3; execve argv and env are exactly as specified (patched `os.execve`) | CLI |

## Docs to update
- `docs/RUNBOOKS/root-owned-release.md`:
  - Steps 2-3 (:66-91), "Roll back" (:95-103) and "Upgrades afterwards" (:105-110) become `apply --plan`, then `apply --confirm`.
  - Remove the wrong "turns ok per unit" claim at :89-90.
  - Bootstrap (:56-64) stays manual.
- `docs/RUNBOOKS/emergency-rollback.md:39-47, :71-75`: replace the pull, diff and reinstall steps and the restart order with `apply --sha <prev>`.
- `docs/RUNBOOKS/sudo-narrowing.md:56-67`: point at apply for routine sudoers installs, and name the 8452 line (:29 versus deploy/sudoers/argus-operator:81).
- Follow-up PR: the reinstall-unit blocks in docs/MONITORING.md:87-104, docs/BACKUP_AND_RESTORE.md:118-123/:156-161/:191-196, docs/P5_SCHEDULED_SMOKE.md:46-63 and docs/OPERATIONS.md:415-417 say "update via apply". First-time enabling stays manual. Delete the `rm -r` rollback at MONITORING.md:155-156.

## Task breakdown (one issue and PR each)
1. **Skeleton: guards, trust and release activation.** Covers steps 1-5, 8-10 and `verify_existing`, and the history `started`/`finished` writer.
   - AC: `--plan` and `--confirm` work for the release action only; tests 1-4, 6, 7 (release part), 14 and 15 pass; `argus-check` is green.
2. **/etc convergence.** Covers steps 6 and 11: the drift table, backups, sysusers, render_overrides over the desired unit set, and sudoers with visudo.
   - AC: tests 5, 10 and 11 pass; no `.d` dir is ever removed; the digest includes the drift.
3. **Restart, gates, smoke and evidence.** Covers steps 7 and 12-15: the baseline doctor, cascade-aware skip, smoke freshness and scope, the full row schema, and exit 5 semantics.
   - AC: tests 8, 9, 12 and 13 pass; every post-mutation failure exits 5 and prints the rollback command.
4. **CLI shim, sudoers guard and runbooks.** The `release apply` leaf and exec branch, the sudoers assertions, and the root-owned-release and emergency-rollback rewrites.
   - AC: test 16 and the new sudoers tests pass; runbook examples use only `apply`; tests/test_argus_sudoers.py:308 is updated if the `ln -sfn` text moves.
5. **Follow-up docs.** Repoint the reinstall blocks in MONITORING, BACKUP, P5 and OPERATIONS, and extend the sudo-line scan beyond `docs/RUNBOOKS` (tests/test_argus_sudoers.py:235).
   - AC: no doc tells the operator to `install` a repo unit by hand except first-time enables.

## Owner decisions (2026-11-21)
1. **CI-green gate:** v1 is operator-attested. The operator runs `gh pr view <n> --json mergeCommit,statusCheckRollup` on the laptop, and apply records `checks.source: "operator-attested"`. A machine-checked gate waits for the D028 pull-stager decision (signed commits or a server-side GitHub read).
2. **Signed evidence (D022):** v1 ships unsigned, root-owned history. The gap is recorded here and closed in a later PR.
3. **Restart scope:** every apply that moves `current` restarts all active argus daemons in group order, with a doctor gate after each.

---
Not checked: the server's real state; whether systemd on this host cascades `restart` to `Requires=` dependents (step 12 asserts it per unit, so a mismatch shows up as a skipped unit with a stale timestamp, which then gets restarted); branch protection on main. Risk: until question 1 is decided, "checks green" rests on the operator's word.