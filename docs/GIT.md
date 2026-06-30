# Git Workflow

`/srv/oreo-cloud` is the Git-tracked source of truth for P0 platform configuration on `oreochiserver`.

## Repository Rules

- `main` contains reviewed P0 state.
- Each P0 phase uses a dedicated branch and pull request.
- Commits should be small enough to inspect and revert.
- Do not commit workload source, `.env` files, tokens, runtime data, backups, database files, or generated metrics.

## Server Checkout

Expected target path:

```text
/srv/oreo-cloud
```

The server checkout should track:

```text
https://github.com/pxm-0/oreo-cloud.git
```

If `/srv/oreo-cloud` does not exist yet, create it with the operator user as owner, then clone or initialize from this repository.

## Checkpointing

Before and after server-affecting work:

```bash
cd /srv/oreo-cloud
git status --short
git add <intentional-files>
git commit -m "<phase commit message>"
```

Use the commit message from `docs/CODEX_TASKS.md` when a task specifies one.

## Secret Check

Run before each PR:

```bash
git ls-files | grep -E '(^|/)\.env($|\.)|token|credential|secret|\.key$|\.pem$' && exit 1 || true
```

This should print nothing and exit successfully.
