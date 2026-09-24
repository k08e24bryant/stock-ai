# database/schemas

Reference SQL and schema documentation.

**Empty in Phase 0 by design.** The relational schema (tables listed in
CLAUDE.md §22) is designed incrementally starting in Phase 2, table group by
table group, alongside the migration that creates it.

Authoritative schema state lives in `database/migrations/versions/`.
This directory holds human-readable reference material only — entity
diagrams, column semantics, and timestamp conventions (`event_time`,
`publication_time`, `available_at`, `effective_date`) — never a second,
divergent copy of the DDL.
