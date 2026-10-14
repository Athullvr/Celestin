-- Draft empty-database schema spike for hosted Celestin tenancy.
-- Not wired into the SQLite migration runner and not a production migration.
-- Application-generated UUIDs avoid requiring a PostgreSQL extension.
-- archived_at retains rows and source links; purge_after is an eligibility
-- date only. A separately authorized retention workflow must perform purges.
-- Authorization and the last-active-owner invariant require application
-- transactions; these constraints do not authenticate callers.

BEGIN;

CREATE TABLE celestin_users (
    id          UUID PRIMARY KEY,
    issuer      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (issuer, subject)
);

CREATE TABLE celestin_workspaces (
    id          UUID PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    purge_after TIMESTAMPTZ,
    CHECK (purge_after IS NULL OR
        (archived_at IS NOT NULL AND purge_after >= archived_at))
);

CREATE TABLE celestin_workspace_memberships (
    workspace_id UUID NOT NULL REFERENCES celestin_workspaces(id) ON DELETE RESTRICT,
    user_id      UUID NOT NULL REFERENCES celestin_users(id) ON DELETE RESTRICT,
    role         TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    status       TEXT NOT NULL CHECK (status IN ('invited', 'active', 'suspended')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX idx_celestin_workspace_memberships_user
    ON celestin_workspace_memberships (user_id);

CREATE INDEX idx_celestin_workspace_active_owners
    ON celestin_workspace_memberships (workspace_id)
    WHERE role = 'owner' AND status = 'active';

CREATE TABLE celestin_projects (
    id                 UUID PRIMARY KEY,
    workspace_id       UUID NOT NULL REFERENCES celestin_workspaces(id) ON DELETE RESTRICT,
    slug               TEXT NOT NULL,
    legacy_project_key TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at        TIMESTAMPTZ,
    purge_after        TIMESTAMPTZ,
    UNIQUE (workspace_id, slug),
    UNIQUE (workspace_id, legacy_project_key),
    UNIQUE (workspace_id, id),
    CHECK (purge_after IS NULL OR
        (archived_at IS NOT NULL AND purge_after >= archived_at))
);

CREATE TABLE celestin_project_memberships (
    workspace_id UUID NOT NULL,
    project_id   UUID NOT NULL,
    user_id      UUID NOT NULL,
    can_read     BOOLEAN NOT NULL DEFAULT FALSE,
    can_write    BOOLEAN NOT NULL DEFAULT FALSE,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ,
    PRIMARY KEY (project_id, user_id),
    CHECK (NOT can_write OR can_read),
    CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
    FOREIGN KEY (workspace_id, project_id)
        REFERENCES celestin_projects(workspace_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES celestin_workspace_memberships(workspace_id, user_id) ON DELETE RESTRICT
);

CREATE INDEX idx_celestin_project_memberships_workspace_project
    ON celestin_project_memberships (workspace_id, project_id);

CREATE INDEX idx_celestin_project_memberships_workspace_user
    ON celestin_project_memberships (workspace_id, user_id);

CREATE TABLE celestin_service_identities (
    id          UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES celestin_workspaces(id) ON DELETE RESTRICT,
    issuer      TEXT NOT NULL,
    subject     TEXT NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, issuer, subject),
    UNIQUE (workspace_id, id),
    CHECK ((status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL))
);

CREATE TABLE celestin_service_project_grants (
    workspace_id       UUID NOT NULL,
    project_id          UUID NOT NULL,
    service_identity_id UUID NOT NULL,
    can_read            BOOLEAN NOT NULL DEFAULT FALSE,
    can_write           BOOLEAN NOT NULL DEFAULT FALSE,
    granted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    PRIMARY KEY (project_id, service_identity_id),
    CHECK (NOT can_write OR can_read),
    CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
    FOREIGN KEY (workspace_id, project_id)
        REFERENCES celestin_projects(workspace_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, service_identity_id)
        REFERENCES celestin_service_identities(workspace_id, id) ON DELETE RESTRICT
);

CREATE INDEX idx_celestin_service_grants_workspace_project
    ON celestin_service_project_grants (workspace_id, project_id);

CREATE INDEX idx_celestin_service_grants_workspace_identity
    ON celestin_service_project_grants (workspace_id, service_identity_id);

-- Hosted equivalents. Local SQLite integer IDs remain record identifiers only;
-- workspace/project references are always resolved and authorized server-side.
CREATE TABLE chat_messages (
    id              BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    workspace_id    UUID NOT NULL,
    project_id      UUID NOT NULL,
    conversation_id TEXT NOT NULL DEFAULT 'default',
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ,
    purge_after     TIMESTAMPTZ,
    UNIQUE (project_id, id),
    FOREIGN KEY (workspace_id, project_id)
        REFERENCES celestin_projects(workspace_id, id) ON DELETE RESTRICT,
    CHECK (purge_after IS NULL OR
        (archived_at IS NOT NULL AND purge_after >= archived_at))
);

CREATE INDEX idx_chat_messages_workspace_project_conversation
    ON chat_messages (workspace_id, project_id, conversation_id, id);

CREATE TABLE project_memory (
    id                BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    workspace_id      UUID NOT NULL,
    project_id        UUID NOT NULL,
    key               TEXT NOT NULL,
    value             TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'deprecated')),
    source_message_id  BIGINT,
    created_at         TIMESTAMPTZ NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL,
    archived_at        TIMESTAMPTZ,
    purge_after        TIMESTAMPTZ,
    UNIQUE (project_id, key),
    FOREIGN KEY (workspace_id, project_id)
        REFERENCES celestin_projects(workspace_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (project_id, source_message_id)
        REFERENCES chat_messages(project_id, id)
        ON DELETE RESTRICT,
    CHECK (purge_after IS NULL OR
        (archived_at IS NOT NULL AND purge_after >= archived_at))
);

CREATE INDEX idx_project_memory_workspace_project
    ON project_memory (workspace_id, project_id);

-- Supports project-scoped provenance lookups and child-row checks when a
-- referenced chat_messages(project_id, id) row is updated or deleted.
CREATE INDEX idx_project_memory_project_source_message
    ON project_memory (project_id, source_message_id);

COMMIT;
