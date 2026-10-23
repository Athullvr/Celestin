"""Scripted tests for transactional workspace-admin provisioning."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import time
from uuid import UUID

import pytest

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.middleware.bearer_auth import AccessToken

from orbit.mcp_server.hosted_auth import Auth0TokenVerifier, Auth0VerifierConfig
from orbit.postgres.provisioning import (
    HumanProjectCapabilities,
    PostgresAccessProvisioner,
    ProvisioningConflict,
    ProvisioningDenied,
    ServiceProjectCapabilities,
)


ISSUER = "https://celestin-example.auth0.com/"
AUDIENCE = "https://api.celestin.example"
CLIENT_ID = "owner-client"
WORKSPACE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ACTOR_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
TARGET_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SERVICE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class Cursor:
    def __init__(self, row=None):
        self.row = row
        self.closed = False

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class Connection:
    def __init__(
        self,
        *,
        role="admin",
        existing_service=False,
        existing_human=False,
        target_status="active",
        target_membership_role="member",
        target_membership_status="active",
        grant_revoked_at=None,
        service_status="active",
    ):
        self.role = role
        self.existing_service = existing_service
        self.existing_human = existing_human
        self.target_status = target_status
        self.target_membership_role = target_membership_role
        self.target_membership_status = target_membership_status
        self.grant_revoked_at = grant_revoked_at
        self.service_status = service_status
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.close_calls = 0
        self.depth = 0

    def execute(self, query, params=()):
        sql = " ".join(query.split())
        self.calls.append((sql, tuple(params)))
        if sql.startswith("SELECT id FROM celestin_workspaces"):
            row = (WORKSPACE,)
        elif sql.startswith("SELECT id, status FROM celestin_users"):
            row = (ACTOR_ID, "active")
        elif sql.startswith("SELECT role, status FROM celestin_workspace_memberships") and "FOR UPDATE" in sql:
            row = (self.target_membership_role, self.target_membership_status)
        elif sql.startswith("SELECT role, status FROM celestin_workspace_memberships"):
            row = (self.role, "active")
        elif sql.startswith("SELECT id FROM celestin_projects"):
            row = (PROJECT,)
        elif sql.startswith("INSERT INTO celestin_users"):
            row = None if self.existing_human else (params[0],)
        elif sql.startswith("SELECT revoked_at FROM celestin_project_memberships"):
            row = (self.grant_revoked_at,)
        elif sql.startswith("SELECT status FROM celestin_users"):
            row = (self.target_status,)
        elif sql.startswith("SELECT status FROM celestin_service_identities"):
            row = (self.service_status,)
        elif sql.startswith("INSERT INTO celestin_service_identities"):
            row = None if self.existing_service else (params[0],)
        elif sql.startswith("UPDATE celestin_service_identities"):
            self.service_status = "revoked"
            row = (SERVICE_ID,)
        elif "RETURNING project_id" in sql:
            row = (PROJECT,)
        else:
            row = None
        return Cursor(row)

    @contextmanager
    def transaction(self):
        outermost = self.depth == 0
        self.depth += 1
        try:
            yield
        except Exception:
            if outermost:
                self.rollbacks += 1
            raise
        else:
            if outermost:
                self.commits += 1
        finally:
            self.depth -= 1

    def close(self):
        self.close_calls += 1


def verified_admin_token():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update(kid="owner-key", use="sig", alg="RS256")
    config = Auth0VerifierConfig(
        ISSUER,
        AUDIENCE,
        "auth0",
        "RS256",
        "memory:read",
        "memory:write",
        {CLIENT_ID: "human"},
    )
    verifier = Auth0TokenVerifier(
        config,
        fetch_json=lambda url: (
            {"issuer": ISSUER, "jwks_uri": f"{ISSUER}.well-known/jwks.json"}
            if url.endswith("openid-configuration")
            else {"keys": [jwk]}
        ),
    )
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "auth0|admin-1",
            "aud": AUDIENCE,
            "exp": now + 300,
            "iat": now - 1,
            "azp": CLIENT_ID,
            "scope": "memory:write",
        },
        key,
        algorithm="RS256",
        headers={"kid": "owner-key", "typ": "JWT"},
    )
    return asyncio.run(verifier.verify_token(token))


def test_human_access_provisioning_is_locked_project_scoped_and_atomic():
    connection = Connection()
    provisioner = PostgresAccessProvisioner(lambda: connection)

    provisioner.provision_human_project_access(
        verified_admin_token(),
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        user_id=TARGET_ID,
        capabilities=HumanProjectCapabilities(
            can_read=True, can_write=True, can_approve_candidates=True
        ),
    )

    assert connection.commits == 1 and connection.rollbacks == 0
    assert connection.close_calls == 1
    assert any("FOR SHARE" in sql for sql, _ in connection.calls)
    assert any("INSERT INTO celestin_workspace_memberships" in sql for sql, _ in connection.calls)
    grant = next((sql, params) for sql, params in connection.calls if "INSERT INTO celestin_project_memberships" in sql)
    assert grant[1][:3] == (WORKSPACE, PROJECT, TARGET_ID)
    assert grant[1][3:6] == (True, True, True)


def test_human_principal_creation_and_initial_grant_are_atomic():
    connection = Connection()
    provisioner = PostgresAccessProvisioner(lambda: connection)

    user_id = provisioner.provision_human_principal(
        verified_admin_token(),
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        subject="auth0|new-user",
        capabilities=HumanProjectCapabilities(can_read=True, can_write=False),
    )

    create_user = next(call for call in connection.calls if call[0].startswith("INSERT INTO celestin_users"))
    assert user_id == create_user[1][0]
    assert connection.commits == 1 and connection.rollbacks == 0
    assert create_user[1][1:] == (ISSUER, "auth0|new-user")
    assert "'active'" in create_user[0]
    assert any("INSERT INTO celestin_workspace_memberships" in sql for sql, _ in connection.calls)
    assert any("INSERT INTO celestin_project_memberships" in sql for sql, _ in connection.calls)
    assert connection.close_calls == 1


def test_duplicate_human_identity_is_not_reactivated_or_granted():
    connection = Connection(existing_human=True)
    provisioner = PostgresAccessProvisioner(lambda: connection)

    with pytest.raises(ProvisioningConflict, match="already exists"):
        provisioner.provision_human_principal(
            verified_admin_token(),
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            subject="auth0|existing-user",
            capabilities=HumanProjectCapabilities(can_read=True, can_write=False),
        )

    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("INSERT INTO celestin_workspace_memberships" in sql for sql, _ in connection.calls)
    assert not any("INSERT INTO celestin_project_memberships" in sql for sql, _ in connection.calls)
    assert connection.close_calls == 1


def test_workspace_non_admin_cannot_change_memberships_or_grants():
    connection = Connection(role="member")
    provisioner = PostgresAccessProvisioner(lambda: connection)

    with pytest.raises(ProvisioningDenied, match="access denied"):
        provisioner.provision_human_project_access(
            verified_admin_token(),
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            user_id=TARGET_ID,
            capabilities=HumanProjectCapabilities(can_read=True, can_write=False),
        )

    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("INSERT INTO celestin_" in sql for sql, _ in connection.calls)
    assert connection.close_calls == 1


def test_service_identity_and_initial_grant_share_one_transaction():
    connection = Connection()
    provisioner = PostgresAccessProvisioner(lambda: connection)

    service_id = provisioner.register_service_project_access(
        verified_admin_token(),
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        issuer=ISSUER,
        subject="agent-client@clients",
        name="build-agent",
        capabilities=ServiceProjectCapabilities(can_read=True, can_write=False),
    )

    assert service_id != UUID(int=0)
    assert connection.commits == 1 and connection.rollbacks == 0
    identity_index = next(i for i, (sql, _) in enumerate(connection.calls) if "INSERT INTO celestin_service_identities" in sql)
    grant_index = next(i for i, (sql, _) in enumerate(connection.calls) if "INSERT INTO celestin_service_project_grants" in sql)
    assert identity_index < grant_index
    assert connection.close_calls == 1


def test_existing_service_registration_does_not_silently_reactivate_or_grant():
    connection = Connection(existing_service=True)
    provisioner = PostgresAccessProvisioner(lambda: connection)

    with pytest.raises(ProvisioningConflict, match="reactivation is not supported"):
        provisioner.register_service_project_access(
            verified_admin_token(),
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            issuer=ISSUER,
            subject="agent-client@clients",
            name="build-agent",
            capabilities=ServiceProjectCapabilities(can_read=True, can_write=False),
        )

    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("INSERT INTO celestin_service_project_grants" in sql for sql, _ in connection.calls)
    assert connection.close_calls == 1


def test_service_revocation_updates_identity_once_and_is_repeatable():
    connection = Connection()
    provisioner = PostgresAccessProvisioner(lambda: connection)

    for _ in range(2):
        provisioner.revoke_service_identity(
            verified_admin_token(), workspace_id=WORKSPACE, service_identity_id=SERVICE_ID
        )

    assert connection.commits == 2 and connection.rollbacks == 0
    assert sum("SET status = 'revoked'" in sql for sql, _ in connection.calls) == 1
    assert sum("UPDATE celestin_service_project_grants" in sql for sql, _ in connection.calls) == 1
    assert connection.close_calls == 2


def test_human_project_grant_revocation_is_repeatable():
    connection = Connection(grant_revoked_at=None)
    provisioner = PostgresAccessProvisioner(lambda: connection)

    for attempt in range(2):
        connection.grant_revoked_at = None if attempt == 0 else "already-revoked"
        provisioner.revoke_human_project_access(
            verified_admin_token(),
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            user_id=TARGET_ID,
        )

    assert connection.commits == 2 and connection.rollbacks == 0
    assert sum("SET revoked_at = clock_timestamp()" in sql for sql, _ in connection.calls) == 1
    assert connection.close_calls == 2


def test_workspace_membership_revocation_rejects_owner_and_revokes_grants():
    owner_connection = Connection(target_membership_role="owner")
    owner_provisioner = PostgresAccessProvisioner(lambda: owner_connection)
    with pytest.raises(ProvisioningDenied, match="access denied"):
        owner_provisioner.revoke_human_workspace_membership(
            verified_admin_token(), workspace_id=WORKSPACE, user_id=TARGET_ID
        )
    assert owner_connection.rollbacks == 1 and owner_connection.commits == 0
    assert not any("UPDATE celestin_project_memberships" in sql for sql, _ in owner_connection.calls)

    connection = Connection(target_membership_status="active")
    provisioner = PostgresAccessProvisioner(lambda: connection)
    provisioner.revoke_human_workspace_membership(
        verified_admin_token(), workspace_id=WORKSPACE, user_id=TARGET_ID
    )
    assert connection.commits == 1 and connection.rollbacks == 0
    assert any("SET status = 'suspended'" in sql for sql, _ in connection.calls)
    assert any("UPDATE celestin_project_memberships" in sql for sql, _ in connection.calls)


def test_caller_constructed_access_token_cannot_impersonate_admin():
    connection_calls = []
    provisioner = PostgresAccessProvisioner(lambda: connection_calls.append(True))
    forged = AccessToken(
        token="not-verified",
        client_id=CLIENT_ID,
        scopes=["memory:write"],
        claims={"iss": ISSUER, "sub": "auth0|admin-1", "_celestin_principal_kind": "human"},
    )

    with pytest.raises(ProvisioningDenied, match="access denied"):
        provisioner.revoke_service_identity(
            forged, workspace_id=WORKSPACE, service_identity_id=SERVICE_ID
        )
    assert connection_calls == []
