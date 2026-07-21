# Argus M4 Safe Migration Planner

The M4 planner is read-only. It refuses a cutover plan until isolated-pilot,
backup, restore, source/target fencing, UID/GID, checksums, health, access,
drift, rollback, and opaque physical runtime/volume mappings are all present.
It emits no shell commands and never stops a workload, copies data, or changes
a route.
