# PostgreSQL migration foundation

## Scope and status

Celestin's local SQLite behavior is unchanged. `orbit.database.engine.connect()` continues to apply only its existing ordered SQLite migrations via `PRAGMA user_version`. Neither MCP server startup nor an MCP request imports the PostgreSQL driver or applies PostgreSQL migrations.

The explicit `celestin-migrate` command applies packaged, ordered PostgreSQL SQL files. `0001_hosted_baseline.sql` is a separately versioned copy of the current hosted-schema draft for a **new, empty database**. Migration `0002_user_status.sql` additively adds human identity status with a `suspended` default and an `active|suspended` check; existing identities are not silently enabled. Migration `0003_retrieval_search_indexes.sql` adds partial GIN expression indexes for active message content and decision values using PostgreSQL's `simple` text-search configuration. It is additive and can be reversed by dropping those two named indexes, but the runner has no automatic downgrade mechanism; any production rollback procedure must be separately reviewed. These migrations remain a draft, are not approved for production use, and should only be applied after the team approves the target schema. The source draft at `docs/hosted-tenancy-schema.sql` remains unchanged and is not executed by this runner. Once applied anywhere, a migration file is immutable: make schema changes in a new numbered file.

The migration foundation and retrieval adapter are not a hosted application, authentication mechanism, data importer, or production deployment. A separately injectable `PostgresMemoryStore` implements the existing message/decision persistence port; `PostgresRetrievalData` implements the retrieval-data port with explicit workspace/project scope. `PostgresHostedAuthorizationSessionFactory` provides a transaction-scoped authorization session. None of these components is selected by the MCP server. The authorization session and retrieval adapter have unit tests only; neither has been tested against PostgreSQL. MCP retrieval remains SQLite-backed. The hosted schema still does not enforce application authorization or the last-active-workspace-owner policy by itself.

## Install and explicitly initialize a new database

Install the optional driver extra in the environment used for administration:

```powershell
python -m pip install -e ".[postgres]"
```

Provision a dedicated PostgreSQL database first. Supply its DSN to the command through the operator's approved secret manager or secure local environment setup; do not put credentials in the repository, command-line arguments, logs, or checked-in configuration. The command reads `CELESTIN_POSTGRES_DSN` by default and accepts `--dsn-env NAME` to use another environment variable name.

```powershell
# Set CELESTIN_POSTGRES_DSN from your approved local secret source.
celestin-migrate
```

On success, the command prints the migration version and applied versions, not the DSN. It acquires a PostgreSQL session advisory lock. When no ledger exists, it first checks for user schemas, table/view/sequence/foreign-table relations, procedures, and user types without excluding ledger-named objects. It then creates `public.celestin_schema_migrations` and performs a second check. PostgreSQL creates a composite row type and associated array type for a table ([type catalog](https://www.postgresql.org/docs/18/catalog-pg-type.html), [type system](https://www.postgresql.org/docs/18/extend-type-system.html)). The second check ignores only the ledger table and the exact array type identified through that row type's `typarray` OID; unrelated relations and types still cause a refusal. It then applies each pending migration and its ledger row in one transaction with the migration schema pinned to `public`. If a populated ledger already exists, versions and SHA-256 checksums are checked before pending migrations run. A pre-existing empty ledger is ambiguous and is refused rather than adopted. The ledger records `version`, `name`, `checksum`, and the server-side `applied_at` timestamp.

Migration DDL must be transactional. A failed migration rolls back its own DDL and ledger insert; earlier successful versions remain recorded and may be resumed after the cause is corrected. The initial ledger creation commits before version 1 starts, so a failure before any migration is recorded can leave an empty ledger. Do not rerun against or manually adopt that database; preserve it for inspection and ask the database owner to provision a new disposable database for a later authorized attempt. The session lock is released when the runner exits. Do not edit an applied migration to repair it: restore the exact original file and add a new migration for a forward correction.

## Existing databases without a ledger

The runner fails closed if it finds user objects but no Celestin ledger. It does not infer that an existing schema matches the baseline, create a ledger over it, or attempt adoption. In particular, do not point it at `celestin_schema_test_v2` or another database where the hosted schema was applied manually. First take a verified backup, inspect the complete schema and data, and prepare a separately reviewed adoption procedure that compares every object and records the exact baseline checksum. That adoption procedure is not implemented here. Until then, use only a newly provisioned empty database for initialization.

## Tests and verification boundary

`tests/postgres/test_migration_runner.py` uses an in-memory fake connection to check ordering, checksum drift, repeat application, refusal of untracked objects, rollback behavior, and serialization logic. `tests/postgres/test_migrate_cli.py` checks the missing-DSN path. These fake tests do not establish that PostgreSQL accepts the SQL or that row/advisory locks behave as intended on independent real sessions. The explicitly opted-in live test procedure, target safeguards, commands, and limitations are documented in [PostgreSQL integration tests](postgres-integration-tests.md). It applies migrations only to one pre-provisioned fresh disposable database and does not drop or truncate it.

No SQLite rows are imported. A separate import design must resolve legacy SQLite integer-ID collisions, tenant/project mapping, timestamp/time-zone backfill, source-message links, and rebuildable FTS/vector/PageIndex indexes before any data transfer is attempted.
