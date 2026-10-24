"""Offline structural assessment for a future hosted-project onboarding flow.

This module consumes caller-supplied catalog snapshots only. It never opens a
database connection, executes SQL, provisions roles, or grants operational
readiness. Catalog rows are untrusted input; successful checks mean only that
the supplied rows match the current source-level profile validators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from typing import Any, Mapping
from uuid import UUID

from orbit.mcp_server.hosted_server import (
    AUTHORIZATION_ADMIN_ROLE,
    AUTHORIZATION_READER_ROLE,
    PRIVILEGED_GROUP_ROLES,
    PROJECT_RUNTIME_ROLE,
    _validate_advisory_lock_privilege_catalog,
    _validate_authorization_admin_probe,
    _validate_authorization_reader_probe,
    _validate_function_catalog,
    _validate_policy_catalog,
    _validate_privileged_role_membership_catalog,
    _validate_project_runtime_probe,
    _validate_trigger_catalog,
)


_PROFILE_GROUPS = {
    "project_runtime": PROJECT_RUNTIME_ROLE,
    "authorization_reader": AUTHORIZATION_READER_ROLE,
    "authorization_admin": AUTHORIZATION_ADMIN_ROLE,
    "migration": None,
}
_PROFILE_NAMES = frozenset(_PROFILE_GROUPS)
_LOGIN_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DATABASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIAGNOSTIC_MESSAGES = {
    "invalid_request": "The onboarding request is incomplete or malformed.",
    "project_binding_mismatch": "Requested and configured project scope do not match.",
    "invalid_configuration": "Required project configuration metadata is invalid.",
    "invalid_role_inventory": "The configured role-profile inventory is invalid.",
    "missing_role_profile": "A role profile required for this assessment is missing.",
    "invalid_expected_roster": "The expected privileged-role roster is incomplete or invalid.",
    "missing_catalog_evidence": "Required catalog evidence is missing.",
    "contradictory_catalog_evidence": (
        "Catalog evidence is duplicated or contradicts its configured target."
    ),
    "stale_catalog_evidence": "Catalog evidence is outside the configured freshness window.",
    "catalog_profile_invalid": (
        "A supplied role or privilege catalog does not match the reviewed profile."
    ),
    "policy_catalog_invalid": (
        "The supplied row-security catalog does not match the reviewed profile."
    ),
    "trigger_catalog_invalid": (
        "The supplied authorization-trigger catalog does not match the reviewed profile."
    ),
    "function_catalog_invalid": (
        "The supplied authorization-function catalog does not match the reviewed profile."
    ),
    "lock_scope_unverified": (
        "The function catalog matches its definition, but trusted advisory-lock scope "
        "remains unverified."
    ),
    "role_membership_catalog_invalid": (
        "The supplied privileged-role roster does not match the configured roster."
    ),
    "provider_capability_unverified": (
        "Provider advisory-lock and ownership capabilities remain unverified."
    ),
    "provider_capability_unsupported": "The configured provider capability is marked unsupported.",
    "live_verification_required": (
        "Offline evidence cannot authorize hosted request serving or provisioning."
    ),
}


@dataclass(frozen=True)
class HostedOnboardingRequest:
    """Non-secret request values to compare with operator configuration."""

    workspace_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True)
class HostedProjectConfiguration:
    """Allowlisted, non-secret metadata for one project onboarding assessment.

    Connection strings and credentials are intentionally not accepted by this
    type. ``provider_capability`` is an assertion only and is never trusted as
    provider evidence by this offline evaluator.
    """

    workspace_id: str | None = None
    project_id: str | None = None
    database_identity: str | None = None
    provider_name: str | None = None
    expected_schema_version: int | None = None
    profile_logins: Mapping[str, str] = field(default_factory=dict)
    expected_group_members: tuple[tuple[str, str], ...] = ()
    max_evidence_age_seconds: int | None = None
    provider_capability: str = "unknown"


@dataclass(frozen=True)
class HostedProfileCatalogEvidence:
    """Raw, untrusted role-probe and advisory ACL rows for one login profile."""

    profile: str
    login_name: str
    role_probe_row: tuple[Any, ...] | None = None
    advisory_lock_rows: tuple[tuple[Any, ...], ...] | None = None
    workspace_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True)
class HostedCatalogEvidence:
    """A supplied offline export; this type does not attest to its origin."""

    database_identity: str | None = None
    schema_version: int | None = None
    observed_at: datetime | None = None
    profiles: tuple[HostedProfileCatalogEvidence, ...] = ()
    function_catalog_rows: Mapping[str, tuple[tuple[Any, ...], ...]] = field(
        default_factory=dict
    )
    policy_catalog_rows: tuple[tuple[Any, ...], ...] | None = None
    trigger_catalog_rows: tuple[tuple[Any, ...], ...] | None = None
    privileged_role_membership_rows: tuple[tuple[Any, ...], ...] | None = None


@dataclass(frozen=True)
class ReadinessAssessment:
    """Structural result only; a pass is not a live readiness attestation."""

    status: str
    diagnostics: tuple[str, ...]

    @property
    def profile_structure_status(self) -> str:
        """Separate matching role/catalog rows from unresolved lock policy."""
        if set(self.diagnostics).issubset({"lock_scope_unverified"}):
            return "STRUCTURAL_PASS"
        return "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "profile_structure_status": self.profile_structure_status,
            "diagnostics": [
                {"code": code, "message": _DIAGNOSTIC_MESSAGES[code]}
                for code in self.diagnostics
            ],
        }


@dataclass(frozen=True)
class HostedReadinessReport:
    """Independent offline assessments and an always-closed operational gate."""

    onboarding: ReadinessAssessment
    request_runtime: ReadinessAssessment
    privileged_preflight: ReadinessAssessment

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_level": "offline_structural_only",
            "live_database_verified": False,
            "service_permitted": False,
            "provisioning_permitted": False,
            "operational_status": "BLOCKED",
            "request_runtime": self.request_runtime.as_dict(),
            "privileged_preflight": self.privileged_preflight.as_dict(),
            "onboarding": self.onboarding.as_dict(),
            "operational_diagnostics": [
                {
                    "code": "provider_capability_unverified",
                    "message": _DIAGNOSTIC_MESSAGES["provider_capability_unverified"],
                },
                {
                    "code": "live_verification_required",
                    "message": _DIAGNOSTIC_MESSAGES["live_verification_required"],
                },
            ],
        }


def assess_hosted_onboarding(
    request: HostedOnboardingRequest,
    configuration: HostedProjectConfiguration,
    evidence: HostedCatalogEvidence,
    *,
    now: datetime,
) -> HostedReadinessReport:
    """Assess supplied evidence without connecting, provisioning, or enabling.

    Request-runtime assessment requires only the project-runtime and
    authorization-reader profiles. Privileged preflight separately requires
    the authorization-admin and migration profiles plus the expected group
    roster. A structural pass in either path never permits serving requests.
    """
    if not isinstance(request, HostedOnboardingRequest) or not isinstance(
        configuration, HostedProjectConfiguration
    ):
        blocked = _assessment(["invalid_request"])
        return HostedReadinessReport(blocked, blocked, blocked)

    onboarding_codes, inventory_codes, scope = _validate_onboarding(
        request, configuration
    )
    common_codes = list(onboarding_codes)
    if not common_codes:
        common_codes.extend(_validate_evidence_envelope(configuration, evidence, now))
    profiles, profile_codes = _index_profiles(evidence)

    onboarding = _assessment(onboarding_codes + inventory_codes)
    if onboarding_codes or not isinstance(evidence, HostedCatalogEvidence):
        failure_codes = onboarding_codes or ["missing_catalog_evidence"]
        runtime = _assessment(failure_codes)
        privileged = _assessment(failure_codes)
    else:
        runtime_codes = list(common_codes)
        runtime_codes.extend(profile_codes)
        runtime_codes.extend(
            _assess_runtime_profiles(configuration, evidence, profiles, scope)
        )
        privileged_codes = list(common_codes)
        privileged_codes.extend(profile_codes)
        privileged_codes.extend(
            _assess_privileged_profiles(configuration, evidence, profiles)
        )
        runtime = _assessment(runtime_codes)
        privileged = _assessment(privileged_codes)

    return HostedReadinessReport(onboarding, runtime, privileged)


def _validate_onboarding(
    request, configuration
) -> tuple[list[str], list[str], tuple[UUID | None, UUID | None]]:
    codes: list[str] = []
    inventory_codes: list[str] = []
    try:
        requested_workspace = _parse_uuid(request.workspace_id)
        requested_project = _parse_uuid(request.project_id)
        configured_workspace = _parse_uuid(configuration.workspace_id)
        configured_project = _parse_uuid(configuration.project_id)
    except (AttributeError, TypeError, ValueError):
        codes.append("invalid_request")
        requested_workspace = requested_project = None
        configured_workspace = configured_project = None
    if requested_workspace is not None and requested_project is not None:
        if (requested_workspace, requested_project) != (
            configured_workspace,
            configured_project,
        ):
            codes.append("project_binding_mismatch")

    if (
        not isinstance(configuration.database_identity, str)
        or not _DATABASE_ID.fullmatch(configuration.database_identity)
        or not isinstance(configuration.provider_name, str)
        or not configuration.provider_name.strip()
        or type(configuration.expected_schema_version) is not int
        or configuration.expected_schema_version < 1
        or type(configuration.max_evidence_age_seconds) is not int
        or configuration.max_evidence_age_seconds < 1
        or not isinstance(configuration.provider_capability, str)
        or configuration.provider_capability not in {
            "unknown", "supported", "unsupported"
        }
    ):
        codes.append("invalid_configuration")

    if not isinstance(configuration.profile_logins, Mapping):
        codes.append("invalid_role_inventory")
    else:
        valid_login_values = True
        for profile, login in configuration.profile_logins.items():
            if (
                not isinstance(profile, str)
                or profile not in _PROFILE_NAMES
                or not isinstance(login, str)
                or not _LOGIN_NAME.fullmatch(login)
            ):
                codes.append("invalid_role_inventory")
                valid_login_values = False
                break
        if (
            valid_login_values
            and len(set(configuration.profile_logins.values()))
            != len(configuration.profile_logins)
        ):
            codes.append("invalid_role_inventory")
        if set(configuration.profile_logins) != _PROFILE_NAMES:
            inventory_codes.append("invalid_role_inventory")

    return (
        _unique(codes),
        _unique(inventory_codes),
        (requested_workspace, requested_project),
    )


def _validate_evidence_envelope(configuration, evidence, now) -> list[str]:
    if not isinstance(evidence, HostedCatalogEvidence):
        return ["missing_catalog_evidence"]
    codes: list[str] = []
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not isinstance(evidence.observed_at, datetime)
        or evidence.observed_at.tzinfo is None
        or evidence.observed_at.utcoffset() is None
    ):
        return ["missing_catalog_evidence"]
    if (
        evidence.database_identity != configuration.database_identity
        or evidence.schema_version != configuration.expected_schema_version
    ):
        codes.append("contradictory_catalog_evidence")
    try:
        age = now - evidence.observed_at
    except (OverflowError, TypeError, ValueError):
        return ["missing_catalog_evidence"]
    if (
        age < timedelta(0)
        or age.total_seconds() > configuration.max_evidence_age_seconds
    ):
        codes.append("stale_catalog_evidence")
    if configuration.provider_capability == "unsupported":
        codes.append("provider_capability_unsupported")
    return _unique(codes)


def _index_profiles(evidence) -> tuple[dict[str, HostedProfileCatalogEvidence], list[str]]:
    if not isinstance(evidence, HostedCatalogEvidence):
        return {}, ["missing_catalog_evidence"]
    indexed: dict[str, HostedProfileCatalogEvidence] = {}
    codes: list[str] = []
    try:
        for profile in evidence.profiles:
            if not isinstance(profile, HostedProfileCatalogEvidence):
                codes.append("missing_catalog_evidence")
                continue
            if profile.profile not in _PROFILE_NAMES or profile.profile in indexed:
                codes.append("contradictory_catalog_evidence")
                continue
            indexed[profile.profile] = profile
    except (TypeError, AttributeError):
        codes.append("missing_catalog_evidence")
    return indexed, _unique(codes)


def _assess_runtime_profiles(configuration, evidence, profiles, scope) -> list[str]:
    codes: list[str] = []
    for profile_name in ("project_runtime", "authorization_reader"):
        profile = _get_profile(configuration, profiles, profile_name, codes)
        if profile is None:
            continue
        if profile_name == "project_runtime" and not _project_scope_matches(
            profile, scope
        ):
            codes.append("contradictory_catalog_evidence")
            continue
        _check_advisory_profile(profile, profile_name, codes)
        role_probe = _require_role_probe(profile, codes)
        if role_probe:
            try:
                if profile_name == "project_runtime":
                    _validate_project_runtime_probe(profile.role_probe_row)
                else:
                    _validate_authorization_reader_probe(profile.role_probe_row)
            except Exception:
                codes.append("catalog_profile_invalid")

    project_functions = _function_rows(evidence, "project_runtime", codes)
    if project_functions is not None:
        try:
            _validate_function_catalog(project_functions, project_runtime=True)
        except Exception as error:
            codes.append(_function_failure_code(error))
    reader_functions = _function_rows(evidence, "authorization_reader", codes)
    if reader_functions is not None:
        try:
            _validate_function_catalog(reader_functions, project_runtime=False)
        except Exception as error:
            codes.append(_function_failure_code(error))
    try:
        if evidence.policy_catalog_rows is None:
            raise RuntimeError
        _validate_policy_catalog(evidence.policy_catalog_rows)
    except Exception:
        codes.append("policy_catalog_invalid")
    try:
        if evidence.trigger_catalog_rows is None:
            raise RuntimeError
        _validate_trigger_catalog(evidence.trigger_catalog_rows)
    except Exception:
        codes.append("trigger_catalog_invalid")
    return codes


def _assess_privileged_profiles(configuration, evidence, profiles) -> list[str]:
    codes: list[str] = []
    for profile_name in ("authorization_admin", "migration"):
        profile = _get_profile(configuration, profiles, profile_name, codes)
        if profile is None:
            continue
        _check_advisory_profile(profile, profile_name, codes)
        if profile_name == "authorization_admin":
            _require_role_probe(profile, codes)
            try:
                _validate_authorization_admin_probe(profile.role_probe_row)
            except Exception:
                codes.append("catalog_profile_invalid")
            rows = _function_rows(evidence, profile_name, codes)
            if rows is not None:
                try:
                    _validate_function_catalog(
                        rows, project_runtime=False, authorization_admin=True
                    )
                except Exception as error:
                    codes.append(_function_failure_code(error))

    try:
        _validate_expected_roster(configuration)
    except Exception:
        codes.append("invalid_expected_roster")
    try:
        if evidence.privileged_role_membership_rows is None:
            raise RuntimeError
        _validate_privileged_role_membership_catalog(
            evidence.privileged_role_membership_rows,
            expected_members=set(configuration.expected_group_members),
        )
    except Exception:
        codes.append("role_membership_catalog_invalid")

    # Privileged preflight also validates the shared database definitions. It
    # is deliberately independent of request-profile ACL evidence.
    try:
        if evidence.policy_catalog_rows is None:
            raise RuntimeError
        _validate_policy_catalog(evidence.policy_catalog_rows)
    except Exception:
        codes.append("policy_catalog_invalid")
    try:
        if evidence.trigger_catalog_rows is None:
            raise RuntimeError
        _validate_trigger_catalog(evidence.trigger_catalog_rows)
    except Exception:
        codes.append("trigger_catalog_invalid")
    return codes


def _get_profile(configuration, profiles, profile_name, codes):
    profile = profiles.get(profile_name)
    if profile is None:
        codes.append("missing_role_profile")
        return None
    expected_login = configuration.profile_logins.get(profile_name)
    if expected_login is None:
        codes.append("missing_role_profile")
        return None
    if profile.login_name != expected_login:
        codes.append("contradictory_catalog_evidence")
        return None
    return profile


def _require_role_probe(profile, codes) -> bool:
    if profile.role_probe_row is None:
        codes.append("missing_catalog_evidence")
        return False
    return True


def _project_scope_matches(profile, scope) -> bool:
    try:
        return (
            _parse_uuid(profile.workspace_id),
            _parse_uuid(profile.project_id),
        ) == scope
    except (AttributeError, TypeError, ValueError):
        return False


def _check_advisory_profile(profile, profile_name, codes) -> None:
    if profile.advisory_lock_rows is None:
        codes.append("missing_catalog_evidence")
        return
    try:
        _validate_advisory_lock_privilege_catalog(
            profile.advisory_lock_rows, role_profile=profile_name
        )
        expected_login = profile.login_name
        if any(
            len(row) != 9 or row[7] != expected_login
            for row in profile.advisory_lock_rows
        ):
            raise RuntimeError
    except Exception:
        codes.append("catalog_profile_invalid")


def _function_rows(evidence, profile_name, codes):
    try:
        rows = evidence.function_catalog_rows.get(profile_name)
    except (AttributeError, TypeError):
        rows = None
    if rows is None:
        codes.append("missing_catalog_evidence")
    return rows


def _function_failure_code(error: Exception) -> str:
    if str(error) == "PostgreSQL authorization helper lock-key scope is not verified":
        return "lock_scope_unverified"
    return "function_catalog_invalid"


def _validate_expected_roster(configuration) -> None:
    members = configuration.expected_group_members
    if not isinstance(members, tuple) or any(
        not isinstance(member, tuple)
        or len(member) != 2
        or member[0] not in PRIVILEGED_GROUP_ROLES
        or not isinstance(member[1], str)
        or not _LOGIN_NAME.fullmatch(member[1])
        for member in members
    ):
        raise RuntimeError
    if len(set(members)) != len(members):
        raise RuntimeError
    required = {
        (_PROFILE_GROUPS[profile], login)
        for profile, login in configuration.profile_logins.items()
        if _PROFILE_GROUPS[profile] is not None
    }
    if not required.issubset(set(members)):
        raise RuntimeError
    configured_logins = configuration.profile_logins
    exact_control_members = {
        AUTHORIZATION_READER_ROLE: configured_logins.get("authorization_reader"),
        AUTHORIZATION_ADMIN_ROLE: configured_logins.get("authorization_admin"),
    }
    for group, login in members:
        if group in exact_control_members and exact_control_members[group] != login:
            raise RuntimeError
        if login == configured_logins.get("migration"):
            raise RuntimeError
    if {group for group, _login in members} != set(PRIVILEGED_GROUP_ROLES):
        raise RuntimeError


def _assessment(codes) -> ReadinessAssessment:
    normalized = tuple(_unique(codes))
    return ReadinessAssessment(
        status="STRUCTURAL_PASS" if not normalized else "BLOCKED",
        diagnostics=normalized,
    )


def _parse_uuid(value) -> UUID:
    if not isinstance(value, str) or not value:
        raise ValueError
    return UUID(value)


def _unique(codes) -> list[str]:
    return list(dict.fromkeys(code for code in codes if code in _DIAGNOSTIC_MESSAGES))
