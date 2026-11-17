# Argus dashboard design contract

Status: PR 5A prototype contract. It defines presentation requirements, not D1 observation or M1 migration response schemas.

## Direction

Argus is a calm, exacting private operations console. The first screen answers: is the estate safe, is the evidence complete and fresh, what needs attention, and what exists? Watchfulness comes from the eye mark and evidence language, not ornamental sci-fi styling.

The routine workload row contains identity, trust domain, health, effective access and drift, evidence freshness, and one Inspect action. Evidence, history, previews, and mutations stay behind workload detail. Only Refresh estate is primary in the global header.

## Visual system

- Native UI sans-serif for interface copy; native monospace only for identifiers, code, and measurements.
- Base surfaces: `#070a12`, `#0d1324`, `#141d33`; primary text `#f3f6fc`; secondary text `#9aa8bf`.
- Links/focus use blue, success uses green, caution/stale uses gold, and danger/conflict uses red. Every state also has an explicit text label.
- Corners remain compact at 6px for controls. Cards are not the default page scaffold. Decorative glow, numbering, gradients, and nested cards are excluded.
- All interactive targets are at least 44 by 44 CSS pixels and use a visible 3px focus outline.

## Semantic mappings

| Axis | Required labels |
| --- | --- |
| Health | Healthy, Degraded, Down, Unknown |
| Freshness | Fresh, Stale, Never observed |
| Completeness | Complete, Partial, Failed, Excluded |
| Policy | Allowed, Blocked, Conflict |
| Operation | Queued, Approval required, Running, Succeeded, Failed safe, Indeterminate, Recovery required |
| Privacy | Unclassified, Internal, Sensitive, Restricted |

Health maps `ok: true` to Healthy, `ok: false` to Down, and anything else to Unknown with the reason (check configured but not observed, or no check). No health source reports Degraded yet. Down rows sort first and carry a red edge plus the Down label.

Freshness: health evidence is Stale after 15 minutes (three missed runs of `argus-typed-health.timer`); the dashboard state itself is Stale after 90 seconds (three missed 30-second state polls) or when it reports no `generatedAt`. Never observed means no timestamp was recorded.

## What is broken

The Exceptions tile counts, and names under the number: open `page`/`critical` alerts, workloads whose last health check failed, access drift, unclassified workloads, no domain agent available while workloads exist, and estate evidence that is Empty, Conflict, or Error. It turns red above zero and reads "None open" at zero.

The topbar always shows the dashboard state badge (Fresh, Stale, Unavailable) with "State as of" time and age, including while a workload is open. State re-polls every 30 seconds (slower in a hidden tab). Auto-refresh pauses, and says so, while admin mode is on, a workload detail is open, or a dashboard field holds input, so a refresh never discards typed confirmations. If a load fails, a "State unavailable" alert with Retry appears; previously loaded data stays visible and marked Unavailable, and with no prior state every panel says "Unavailable" instead of loading.

## State and responsive contracts

The fixture-backed prototype covers loading, empty, error, partial, stale, conflict, and success for overview, workload detail, and estate coverage. Fixture fields are illustrative and must not be imported as API or repository schemas.

Validate 320, 375, 768, 1024, and 1440px widths. Below 760px, workload rows become labeled records, detail becomes full width, and the wide comparison matrix is not the primary interaction. Without JavaScript, render only Argus identity and “JavaScript required”; show no estate data, cached state, credential field, or operation control.

## Journey baselines

These baselines are measured from the pre-PR 5A repeated-card surface and are targets for PR 5B refinement.

| Journey | Before | PR 5A prototype path |
| --- | --- | --- |
| Investigate stale discovery | scan summary, topology, repeated workload cards, then evidence | scan exception/freshness row, Inspect, Evidence |
| Diagnose access drift | compare three access cells in each card | read row drift label, Inspect, Evidence |
| Recover failed operation | locate workload card, history, result panel, then mutation controls | Inspect, History, open durable operation; recovery remains fenced |

Secret input is never persisted. Back, forward, and reload preserve only the selected workload route. Authority-changing actions retain session, step-up, preview digest, typed confirmation, and durable-operation safeguards.
