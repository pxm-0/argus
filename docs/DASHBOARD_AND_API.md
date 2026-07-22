# Dashboard and Control API

## Dashboard Purpose

The dashboard is the single private access point for Argus.

It should be mobile-first and reachable from Tailscale-connected devices:

```text
http://oreochiserver:8088
```

## Dashboard Sections

P0 dashboard sections:

1. Header / system identity
2. Workload cards
3. Monitor toggle
4. Cloudflare exposure plan
5. Events/audit summary
6. Admin mode panel

## Workload Card Fields

Each workload card should show:

```text
Name
ID
Lifecycle
Runtime type
Migration status
Health
Privacy state
Desired access
Effective access
Local URL
Tailnet URL
Cloudflare URL or planned state
Actions
```

## View-Only Mode

Unauthenticated dashboard mode can:

- view workloads
- open allowed URLs
- view health
- view desired/effective access
- view monitor panel
- view Cloudflare plan

It cannot mutate config.

## Admin Mode

Admin mode asks for a control token. The token is stored in browser `sessionStorage`, not `localStorage`.

Admin mode can:

- update privacy state
- preview access changes
- apply allowed access changes
- regenerate dashboard indirectly through API actions

Admin mode cannot:

- bypass policy
- expose blocked targets
- print token
- write token into HTML
- expose the control API publicly

## Control API

The control API must bind only to:

```text
127.0.0.1:8099
```

Caddy may proxy `/api/*` through the Tailscale-bound dashboard route.

## Endpoints

### `GET /api/workloads`

Returns merged workload view from:

- `workloads.json`
- `privacy.json`
- `access.json`
- `routes.json`
- `exposure.json`

Auth: optional for read-only.

### `GET /api/access`

Returns access state.

Auth: optional for read-only.

### `GET /api/privacy`

Returns privacy state.

Auth: optional for read-only.

### `POST /api/workloads/<id>/privacy`

Body:

```json
{
  "privacy": "sensitive",
  "reason": "Operator change"
}
```

Auth: required.

Behavior:

1. validate workload id
2. validate privacy state
3. update `privacy.json`
4. write audit event
5. regenerate dashboard
6. optionally Git checkpoint

### `POST /api/workloads/<id>/access/preview`

Body:

```json
{
  "desired": "cloudflare-protected"
}
```

Auth: required.

Behavior:

1. read workload, privacy, access, policy
2. return allowed/blocked decision
3. list files/routes that would change
4. do not modify anything

### `POST /api/workloads/<id>/access/apply`

Body:

```json
{
  "desired": "tailnet",
  "confirmation": ""
}
```

Auth: required.

Behavior:

1. validate transition
2. verify confirmation phrase when required
3. update `access.json.desired`
4. apply safe states
5. update `access.json.effective` only after success
6. write audit event
7. regenerate dashboard
8. optionally Git checkpoint

For P0, `cloudflare-protected` and `cloudflare-public` should generally update desired state and generate a plan, but not become effective unless Cloudflare activation has been explicitly implemented and enabled.

### `GET /api/metrics`

Returns `metrics.json`.

Auth: optional if dashboard is private, but still safe metrics only.

### `GET /api/events`

Returns sanitized recent audit events.

Auth: optional for read-only or required depending on final preference.

## API Auth

Token file:

```text
/etc/argus/control-token
```

Permissions:

```text
root:argus
0640
```

Requests use:

```text
Authorization: Bearer <token>
```

The API must never log the token.

## Audit Events

Audit file:

```text
/srv/argus/runtime/audit.log
```

JSONL format:

```json
{"timestamp":"2026-06-30T00:00:00Z","actor":"admin-token","action":"privacy.set","workloadId":"intake-os","from":"internal","to":"sensitive","result":"ok"}
```

Do not track audit logs in Git.

## Dashboard Mutation Flow

Privacy change:

```text
select new privacy -> POST privacy -> update config -> audit -> regenerate dashboard
```

Access change:

```text
select new access -> preview -> confirmation if needed -> apply -> desired -> route/provider work -> effective -> audit -> regenerate dashboard
```

## Control API Systemd Template

See:

```text
templates/systemd/argus-control-api.service
```
