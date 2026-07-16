# Argus M4 Stateful Migration Evidence

Before a stateful workload can be declared migrated, private evidence must
identify stable logical identity and distinct opaque physical source/target
runtime and volume identities. The validator requires matching SHA-256 data
checksums, translated UID/GID evidence, verified backup and restore, source
fencing, target fencing before rollback, health/access/isolation checks, and a
verified rollback. It rejects incomplete records and never accepts concurrent
writer risk as a waiver.
