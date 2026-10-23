# PostgreSQL integration tests

## Scope

The opt-in PostgreSQL suite exercises the packaged migrations, the authorization/session code, project-scoped runtime identities, and the Evidence/Knowledge adapter against PostgreSQL. `tests/postgres/test_live_authorization.py` covers authorization decisions, same-key project separation, lifecycle/revocation, constraints, in-flight authorization changes, rollback, direct SQL/RLS behavior, legacy-GUC forgery, and prohibited role switching. `tests/postgres/test_live_evidence_store.py` covers Evidence/Knowledge reads and writes, attachment, verification, supersession, project isolation, authorization denial, constraints, savepoints, and outer-transaction rollback.

These tests do not validate Auth0 against a real tenant or prove that hosted MCP has been deployed. They use synthetic principals and test-only scope bindings. Hosted runtime and database behavior must be reviewed separately before release.

## Test modes

Ordinary tests do not connect to PostgreSQL. Run the offline PostgreSQL tests with the repository validation environment:

```powershell
.\.venv\validation\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts='' tests\postgres\test_hosted_authorization.py tests\postgres\test_migration_runner.py tests\postgres\test_migrate_cli.py tests\postgres\test_live_support.py tests\postgres\test_provisioning.py tests\postgres\test_request_unit_of_work.py
```

The live suite is opt-in and skips unless `--run-postgres-integration` is explicitly supplied. When opted in, the session fixture validates all five configured login identities and the target before applying migrations through the repository's guarded migration runner. The command below can create schema objects in the configured database; run it only after a database owner has explicitly approved and provisioned that disposable target.

```powershell
.\.venv\validation\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts='' --run-postgres-integration -m postgres_integration tests\postgres\test_live_authorization.py tests\postgres\test_live_evidence_store.py
```

The fixture never uses SQLite as a fallback, never reads `CELESTIN_POSTGRES_DSN`, and never creates, drops, truncates, or adopts a database. It calls `orbit.postgres.migrations.runner.apply_migrations()` only after confirming the configured migration connection and fresh-database conditions. A skip is not live validation. Do not install optional dependencies as part of a test run without separate authorization.

## Required approved disposable target

The database owner must explicitly approve a newly provisioned local PostgreSQL database for a one-run integration session. The environment variable `CELESTIN_TEST_POSTGRES_DISPOSABLE=true` is an operator assertion; it does not prove approval, freshness, or safety by itself. The harness additionally requires a loopback IP, exact connection coordinates, fresh nonce-based names, distinct logins, safe role attributes, expected group memberships, and a database with no migration ledger or user-created objects.

Migration 0008 expects these pre-provisioned `NOLOGIN` group roles and does not create or drop roles:

- `celestin_project_runtime`
- `celestin_authorization_reader`
- `celestin_authorization_admin`

For each run, provision one fresh database named `celestin_it_YYYYMMDD_<8-hex-nonce>` and five distinct direct logins with that same nonce:

- Migration/database-owner login: `celestin_it_user_<nonce>`
- Authorization-administration login: `celestin_it_admin_<nonce>`
- Read-only authorization login: `celestin_it_reader_<nonce>`
- Project A content login: `celestin_it_project_a_<nonce>`
- Project B content login: `celestin_it_project_b_<nonce>`

Use a new nonce and a new empty database for each initialization attempt. The migration login must be a non-superuser database owner and must not have `CREATEROLE`, `CREATEDB`, `REPLICATION`, `BYPASSRLS`, or additional role memberships beyond PostgreSQL's implicit `pg_database_owner` relationship. The four runtime logins must be direct logins, non-superusers, `NOBYPASSRLS`, non-owning, and members only of their matching group role (with the implicit `pg_database_owner` exception where applicable). They must not be able to switch roles or create objects in protected schemas. The migration fixture verifies the database and runtime connection identities and role memberships before applying anything.

Set these non-secret coordinates for the same PowerShell session that will run pytest. Do not place passwords in DSNs, command history, repository files, or logs. Supply credentials through an approved secret manager or protected libpq password file.

```powershell
$nonce = 'a1b2c3d4' # replace with a newly generated eight-hex nonce
$date = Get-Date -Format 'yyyyMMdd'
$env:CELESTIN_TEST_POSTGRES_DISPOSABLE = 'true'
$env:CELESTIN_TEST_POSTGRES_DATABASE = "celestin_it_${date}_${nonce}"
$env:CELESTIN_TEST_POSTGRES_HOST = '127.0.0.1'
$env:CELESTIN_TEST_POSTGRES_PORT = '5432'
$env:CELESTIN_TEST_POSTGRES_USER = "celestin_it_user_${nonce}"
$env:CELESTIN_TEST_POSTGRES_ADMIN_USER = "celestin_it_admin_${nonce}"
$env:CELESTIN_TEST_POSTGRES_AUTHORIZATION_USER = "celestin_it_reader_${nonce}"
$env:CELESTIN_TEST_POSTGRES_PROJECT_A_USER = "celestin_it_project_a_${nonce}"
$env:CELESTIN_TEST_POSTGRES_PROJECT_B_USER = "celestin_it_project_b_${nonce}"
$target = "host=127.0.0.1 port=5432 dbname=$env:CELESTIN_TEST_POSTGRES_DATABASE"
$env:CELESTIN_TEST_POSTGRES_DSN = "$target user=$env:CELESTIN_TEST_POSTGRES_USER"
$env:CELESTIN_TEST_POSTGRES_ADMIN_DSN = "$target user=$env:CELESTIN_TEST_POSTGRES_ADMIN_USER"
$env:CELESTIN_TEST_POSTGRES_AUTHORIZATION_DSN = "$target user=$env:CELESTIN_TEST_POSTGRES_AUTHORIZATION_USER"
$env:CELESTIN_TEST_POSTGRES_PROJECT_A_DSN = "$target user=$env:CELESTIN_TEST_POSTGRES_PROJECT_A_USER"
$env:CELESTIN_TEST_POSTGRES_PROJECT_B_DSN = "$target user=$env:CELESTIN_TEST_POSTGRES_PROJECT_B_USER"
```

The parser accepts exactly `host`, `port`, `dbname`, and `user` in each DSN; each must match the separate environment variables. Password parameters, URIs, duplicate/unknown parameters, quoted values, and non-loopback hosts are rejected before a database connection is opened. The harness also rejects all historical retired targets listed below. The checked-in boolean and naming pattern are safeguards, not an operator approval mechanism.

Before opting in, independently verify with the database owner that the selected host, database, roles, and credentials identify the approved disposable target. The fixture repeats its checks immediately before its single migration-runner call. If configuration is missing, ambiguous, not loopback, role attributes/membership are unsafe, or the database is not fresh, the suite fails closed without attempting cleanup. Do not run `celestin-migrate` on this test target first; the fixture requires it to be fresh and initializes it once.

The fixture creates synthetic workspaces, projects, identities, grants, scope mappings, messages, decisions, and Evidence rows. It removes the generated project-scope mappings used by the RLS tests, but it does not remove the generated content rows or migration schema. Treat the database as one-run and retire it using the database owner's separately approved cleanup procedure. Pytest does not drop or reset it.

## Retired database targets

The harness explicitly rejects these names; do not reuse or reset them:

- `celestin_schema_test_v2` — former schema-validation target.
- `celestin_it_20261014_a7f3c9` — failed initialization target.
- `celestin_it_20261015_b364bbae` and `celestin_it_20261015_10ac5ae9` — prior live-test targets.
- `celestin_it_20261015_0b8e767c` — prior one-run live target.

The separate `tests/postgres/validate_hosted_schema.sql` script is not an initializer and must not be run without a separately owner-approved, freshly provisioned target. Its historical fixed target is retired. No database is approved by this document.

## Security interpretation and limits

Migration 0008 replaces caller-settable workspace/project GUC policies on twelve tenant tables with policies that compare each row to `celestin_private.project_runtime_scopes` using PostgreSQL `session_user`. The live RLS cases execute direct queries as the two distinct project logins, attempt legacy-GUC forgery, cross-project reads/writes, role switching, and unauthorized scope-map access. They are designed to check isolation even when a tenant predicate is omitted.

The application still centrally holds configured project DSNs. A compromised application process or control-plane credential can choose among those configured project credentials; the database mapping limits each individual login but does not isolate a fully compromised central process or database administration authority. PostgreSQL owners, superusers, `BYPASSRLS` roles, and compromised credential provisioning remain trusted. The test-only `WorkspaceBinding` is not production transport authentication.

Authorization requests and authorization mutations use matching transaction-scoped advisory locks. This allows an already-authorized transaction to complete before a concurrent revocation commits; subsequent requests should observe the change. The live suite contains cross-session revocation ordering cases, but only an actual opted-in PostgreSQL run can establish server behavior.

The local stdio MCP runtime remains SQLite-backed. Hosted mode is separate and remains gated by `CELESTIN_HOSTED_PROJECT_ROLE_ISOLATION_ENABLED`, whose default is false. These tests do not enable hosted mode or establish production readiness.
