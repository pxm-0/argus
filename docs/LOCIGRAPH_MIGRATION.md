# LociGraph Production-Safe Migration

LociGraph remains stopped after the controlled host reboot. Do not restore the
legacy Compose project directly: its current runtime publishes application,
database, and cache ports on wildcard host interfaces and has no approved backup
or restart gate.

## Read-only preflight

Run on `oreochiserver` from `/srv/argus`:

```bash
sudo python3 scripts/argus-locigraph-migration-preflight \
  | python3 -m json.tool
```

An exit status of `1` means the report safely identified unresolved migration
gates. Exit `2` means evidence could not be collected. The report includes only
environment key names, port scopes, mount targets, service names, and boolean
gates; it never emits environment values or Compose stderr.

No migration apply is allowed until all of these are true:

- only the intended frontend is published, bound to loopback;
- PostgreSQL and Redis have no host-published ports;
- named volumes have an approved backup and tested restore;
- persistent restart policy is defined for every service;
- Argus restart policy is explicitly approved;
- the legacy source remains stopped during validation.

Preserve the Compose project name `locigraph`. Do not change public routes,
open router ports, enable Funnel, or expose PostgreSQL, Redis, or Docker.
