# ADR 001: SQLite for relational data, Neo4j for the evidence graph

**Status:** Accepted

**Context:** The only permitted cloud dependency is Amazon Bedrock. Everything else must be local and open source.

**Decision**
- Relational data, audit events and workflow checkpoints live in SQLite, accessed through SQLAlchemy and Alembic with batch mode.
- Because SQLite has no exact decimal type, money is stored as text through `DecimalText` and always handled as `Decimal`.
- Immutable audit events will be enforced with SQLite triggers that block UPDATE and DELETE.
- SQLite runs in WAL mode with foreign keys on. It is a single-writer store, which is fine for a single-node hackathon deployment.
- The financial graph uses Neo4j behind the `GraphRepository` port. Until a Neo4j server is available, `GRAPH_BACKEND=memory` uses an in-memory placeholder. Switching to `neo4j` needs only configuration.
- Embeddings are a placeholder (`EMBEDDINGS_MODE=placeholder`) and are not implemented.

**Consequences:** No Docker is needed for the default setup. Moving to Postgres later only requires changing `DATABASE_URL`, plus reviewing the SQLite-specific triggers.
