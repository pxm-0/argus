# D030 phases 4–5: re-home an accepted workload from staging to prod

Decision: [D030](../ARGUS_V1_DECISIONS.md). Issues #450 (`kadath`) and #451
(`hastur`). Root shell on `oreochiserver`, one workload at a time.

An accepted cutover is tied to its cell by four things: the `domain` in the
workload's `argus-m5-workload-cutover` spec, the root-owned runtime directory
`/var/lib/argus/migration-runtime/<cell>/<workload>/<leaf>/`, the external
named volume holding its state, and the accepted state in
`/var/lib/argus/migration-cutovers/<workload>/{cutover,journal}.json`. The
re-home moves each of them with the writers stopped, then lets the script's
own `--reconcile` start and verify the target. The legacy source fence is
untouched, and the staging copy (containers and volume) stays in place until
acceptance, so rollback is a restart of the staging copy.

Variables used below (kadath values; hastur in its own section):

```text
W=kadath  P=kadath-live  LEAF=177668245f435511
VOL=argus_m5_stage_kadath_postgres_823ef05b75f1  PORT=8443  HEALTH=/
OLD=personal-sandbox  NEW=personal-managed
DOLD="runuser -u argus-$OLD -- docker --host unix:///var/lib/argus/$OLD/docker.sock"
DNEW="runuser -u argus-$NEW -- docker --host unix:///var/lib/argus/$NEW/docker.sock"
RT=/var/lib/argus/migration-runtime  CS=/var/lib/argus/migration-cutovers/$W
```

## 1. Before the release

1. Stop the reconcile timer so it cannot act while the spec and the runtime
   disagree: `systemctl stop argus-m5-workload-$W.timer`.
2. Take a fresh database backup from the current cell (kadath):
   `systemctl start argus-workload-db-backup@$W.service`, then stop its timer.
3. Install the release that carries the new spec domain
   (`argus-release-install --sha <merged sha>`) and fast-forward `/srv/argus`.

## 2. Move

1. **Images.** For every image in the runtime Compose (services and ingress):
   `$DOLD save <id> | $DNEW load`, then `$DNEW image inspect <id>` must return
   the same ID. Stop here on any mismatch; nothing has changed yet.
2. **Fence.** `$DOLD stop` every container of project `$P` (restart policy is
   already `no`) and require all of them `exited`.
3. **State.** `$DNEW volume create $VOL`, then copy as in-namespace root with
   no network, using an image already in both cells:
   `$DOLD run --rm --network none -u 0 --entrypoint tar -v $VOL:/v:ro <img> -C /v -cf - . | $DNEW run --rm -i --network none -u 0 --entrypoint tar -v $VOL:/v <img> -C /v -xpf -`.
   Then compare a manifest of every file's mode, owner, size and SHA-256 taken
   inside each cell; they must be identical.
4. **Runtime files.** Create `$RT/$NEW/$W/$LEAF/ingress` (root, mode 0711 for
   each directory), copy `docker-compose.json`, `docker-compose.json.before`
   and `ingress.json` with `$RT/$OLD/` rewritten to `$RT/$NEW/`, owned
   `root:argus-$NEW` mode 0640.
5. **Accepted state.** Back up `cutover.json` and `journal.json` beside
   themselves (`*.pre-rehome.<stamp>`), then rewrite `runtimeComposePath`,
   `ingressSocketPath` and `targetTrustDomain` to the new cell. Keep
   `finalStagePath` and `firewallBackupPath`: they are history.
6. **Route.** `tailscale serve --bg --yes --https=$PORT unix:$RT/$NEW/$W/$LEAF/ingress/upstream.sock`.
7. **Start.** `/opt/argus/current/scripts/argus-m5-workload-cutover --workload $W --reconcile`.
   It starts the project in the new cell, waits for every healthcheck and the
   socket probe, locks the socket and verifies the tailnet endpoint.

## 3. Verify

- `$DNEW ps` shows every service of `$P` running and healthy; `$DOLD ps -a`
  shows them all `exited`.
- `https://<tailnet name>:$PORT$HEALTH` answers 200.
- Outbound HTTPS from a `$P` service fails (kadath has no egress).
- `systemctl start argus-m5-workload-$W.timer`; the next reconcile succeeds.
- kadath: `systemctl start argus-workload-db-backup@$W.service` succeeds from
  the new cell; start its timer again.

## 4. Rollback (before acceptance)

1. `$DNEW stop` the project's containers (never `down -v`).
2. Restore `cutover.json` and `journal.json` from the `*.pre-rehome.*` copies.
3. Point `/opt/argus/current` back to the previous release and
   `git -C /srv/argus reset --hard <previous sha>`.
4. `tailscale serve --bg --yes --https=$PORT unix:$RT/$OLD/$W/$LEAF/ingress/upstream.sock`,
   then `--reconcile`, which starts the unchanged staging copy.
5. Writes made in the prod copy after cutover are not copied back.

After acceptance, a later change removes the staging containers and volume.

## hastur (phase 5)

`W=hastur P=hastur LEAF=3025de1c50d22033 VOL=<the external volume named in the runtime Compose> PORT=8445 HEALTH=/api/health`.
hastur also binds its sealed credentials from `/etc/argus/workload-credentials/hastur`,
which must be `root:argus-<cell>`: `chgrp -R argus-personal-managed` it with step 5,
and back to `argus-personal-sandbox` on rollback.
After step 7, give the prod cell hastur's declared egress with
`argus-m5-workload-cutover --workload hastur --apply-egress --acknowledge-m5-egress-policy`,
which renders the whole prod policy (including nodens-production's bridge) with
hastur's DNS and HTTPS rules, and apply the prod host guard (`tcp 443`, from
`argus_host_guard.HOST_EGRESS`) with
`argus-m5-sandbox-bootstrap --domain personal-managed --apply-host-guard --acknowledge-host-egress`.
After acceptance, drop both from the staging cell. Verify that hastur reaches
HTTPS and that `nodens-production` and `kadath` do not.
