"""Trusted resolution of an explicit Celestin local project ID to a Git root.

The mapping is supplied by the application (a ``Mapping`` or a JSON object).
No registry is discovered, and identity is never inferred from the current
directory, a path basename, or the environment. Local project IDs are not
hosted project IDs or retrieval project strings unless a separate approved
mapping says so.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class ProjectResolutionError(Exception):
    """Base class for local project resolution failures."""


class InvalidProjectIdError(ProjectResolutionError, ValueError):
    """The requested project ID is blank or malformed."""


class UnknownProjectError(ProjectResolutionError, KeyError):
    """The project ID is not in the trusted mapping."""


class InvalidProjectConfigurationError(ProjectResolutionError, ValueError):
    """The trusted mapping is malformed or ambiguous."""


class InvalidProjectRootError(ProjectResolutionError):
    """The configured root is unavailable or is not the Git worktree root."""


@dataclass(frozen=True)
class LocalProjectBinding:
    project_id: str
    repository_root: Path


def _validate_project_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidProjectIdError("project_id must be a non-empty string")
    if not _PROJECT_ID.fullmatch(value):
        raise InvalidProjectIdError(
            "project_id must be 1-128 characters of letters, digits, '.', '_' or '-', "
            "starting with a letter or digit, with no surrounding whitespace"
        )
    return value


def _normalize_root(project_id: str, value: object) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise InvalidProjectConfigurationError(f"root for {project_id!r} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        raise InvalidProjectConfigurationError(f"root for {project_id!r} must be an absolute path")
    if ".." in path.parts:
        raise InvalidProjectConfigurationError(f"root for {project_id!r} must not contain '..'")
    return Path(os.path.normpath(path))


def _git_environment() -> dict[str, str]:
    # Drop every GIT_* override (GIT_DIR, GIT_WORK_TREE, GIT_CONFIG_*, ...) so Git
    # cannot be redirected, then pin settings that avoid prompts, locks, and fetches.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    return env


class LocalProjectResolver:
    """Map an explicit local project ID to a validated Git worktree root.

    ``roots`` is the trusted configuration: exact project ID to absolute root.
    Use :meth:`from_json` for a JSON object with the same shape. Configuration
    is validated eagerly; roots are validated against Git on every ``resolve``.
    """

    def __init__(self, roots: Mapping[str, str | Path]) -> None:
        if not isinstance(roots, Mapping):
            raise InvalidProjectConfigurationError("project roots must be a mapping")
        configured: dict[str, Path] = {}
        for raw_id, raw_root in roots.items():
            try:
                project_id = _validate_project_id(raw_id)
            except InvalidProjectIdError as exc:
                raise InvalidProjectConfigurationError(f"invalid configured project ID: {exc}") from exc
            configured[project_id] = _normalize_root(project_id, raw_root)
        owners: dict[Path, str] = {}
        for project_id, root in configured.items():
            if root in owners:
                raise InvalidProjectConfigurationError(
                    f"projects {owners[root]!r} and {project_id!r} map to the same root"
                )
            owners[root] = project_id
        self._roots = configured

    @classmethod
    def from_json(cls, text: str) -> LocalProjectResolver:
        """Build from a JSON object such as ``{"my-project": "/abs/path"}``."""

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise InvalidProjectConfigurationError(f"duplicate project ID {key!r}")
                result[key] = value
            return result

        try:
            payload = json.loads(text, object_pairs_hook=reject_duplicates)
        except json.JSONDecodeError as exc:
            raise InvalidProjectConfigurationError("project roots must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidProjectConfigurationError("project roots must be a JSON object")
        return cls(payload)

    def resolve(self, project_id: str) -> LocalProjectBinding:
        project_id = _validate_project_id(project_id)
        configured = self._roots.get(project_id)
        if configured is None:
            raise UnknownProjectError(f"unknown local project {project_id!r}")
        try:
            root = configured.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidProjectRootError(f"root for {project_id!r} is unavailable") from exc
        if not root.is_dir():
            raise InvalidProjectRootError(f"root for {project_id!r} is not a directory")
        top = self._git_toplevel(project_id, root)
        try:
            resolved_top = Path(top).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidProjectRootError(f"Git root for {project_id!r} is unavailable") from exc
        if resolved_top != root:
            raise InvalidProjectRootError(f"root for {project_id!r} must be the Git worktree root")
        return LocalProjectBinding(project_id=project_id, repository_root=root)

    @staticmethod
    def _git_toplevel(project_id: str, root: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=_git_environment(),
            )
        except OSError as exc:
            raise InvalidProjectRootError("Git could not be started") from exc
        top = result.stdout.decode("utf-8", errors="surrogateescape").rstrip("\n")
        if result.returncode or not top:
            raise InvalidProjectRootError(f"root for {project_id!r} is not a Git worktree")
        return top
