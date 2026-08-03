# Public-Safe Acceptance Summaries

Raw server evidence stays on `oreochiserver` under an ignored, access-controlled
runtime path. It is never copied to Git, GitHub, command arguments, or a public
transcript. A PR may contain only the allowlisted summary produced here.

## Contract

The versioned input schema is
`config/schemas/acceptance-summary.schema.json`. It accepts only:

- issue, phase, target class, check ID, and expected run count;
- Git source revision and a UTC capture timestamp;
- an opaque SHA-256 evidence ID for the private evidence bundle;
- per-run ordinal, result, duration, and stable reason code.

Unknown top-level or per-run fields are rejected. There is intentionally no
field for commands, stdout, stderr, addresses, routes, workload identities,
credentials, file paths, or free-form notes.
Input is capped at 65,536 bytes before JSON parsing, duplicate JSON fields are
rejected, and every summary contains exactly three runs. `pass` requires an
empty reason code; `fail` and `blocked` require a compatible stable reason code.

## Emit a summary

Create an ignored local input file that conforms to the schema, then run:

```bash
scripts/argus-acceptance-summary \
  --input runtime/acceptance/issue-270-baseline.json \
  --format markdown
```

Use `--format json` for the versioned `{ok,error,data}` machine envelope. Markdown
success emits exactly one row for the PR template; Markdown failures use the
stable human diagnostic on stderr. Missing/unreadable input exits `4`, rejected
content exits `3`, and invalid invocation exits `2`. Both success formats are
deterministic and include a digest over canonical allowlisted content.

The emitter validates summaries only. It never reads raw evidence, executes a
probe, contacts a server, or mutates runtime state.

## Storage and review

1. Keep raw evidence and the summary input in ignored runtime storage on the
   authoritative host.
2. Retain them according to the linked issue's rollback/audit window.
3. Put only the emitted Markdown row or JSON summary in the PR.
4. Review the private evidence through the approved operator channel when a
   result is disputed; do not broaden the public schema.
5. A missing or rejected summary is `blocked`, not proof that a check passed.
