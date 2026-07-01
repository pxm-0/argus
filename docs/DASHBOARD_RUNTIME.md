# Dashboard Runtime Cleanliness

P5 separates dashboard source from generated dashboard output.

## Dashboard Source

The tracked source of truth is:

```text
control-plane/dashboard/generate_dashboard.py
```

The generator writes a static shell. It does not read audit logs, metrics,
action previews, Cloudflare activation evidence, or runtime health snapshots.

## Generated Static Assets

These files are generated locally and ignored by Git:

```text
control-plane/dashboard/public/index.html
control-plane/dashboard/public/style.css
control-plane/dashboard/public/app.js
```

Regenerate them with:

```bash
python3 control-plane/dashboard/generate_dashboard.py
```

## Runtime State

Dynamic dashboard state is provided by:

```text
GET /api/dashboard-state
```

The same sanitized state can be written for inspection or refresh jobs with:

```bash
scripts/oreo-dashboard-state
```

The script writes:

```text
runtime/dashboard-state.json
```

That file is ignored by Git.

## Included State

The runtime state contains:

- workload registry data
- privacy state
- desired and effective access state
- route and exposure state
- manifest-derived operation and backup state
- last sanitized audit event per workload
- recent sanitized audit event summaries
- monitoring configuration

Secret-like audit fields are redacted by shared audit sanitization before they reach the dashboard state.

## Cleanliness Check

`scripts/smoke-test` verifies the invariant by:

1. Running `python3 control-plane/dashboard/generate_dashboard.py`.
2. Confirming generated static assets exist.
3. Confirming generated static assets are ignored.
4. Running `scripts/oreo-dashboard-state`.
5. Running the generator again.
6. Confirming generation is stable.
7. Confirming `runtime/dashboard-state.json` is ignored.

Expected smoke output includes:

```text
PASS dashboard index.html ignored
PASS dashboard style.css ignored
PASS dashboard app.js ignored
PASS dashboard generation clean
PASS runtime dashboard state ignored
```
