"""Decision repository: canonical project memory persistence."""

from __future__ import annotations

import sqlite3

from orbit.repositories._validation import (
    NotFoundError,
    ValidationError,
    validate_key,
    validate_project,
    validate_source_message_id,
    validate_status,
    validate_value,
    utc_now_iso,
)


class DecisionRepository:
    """CRUD for the ``project_memory`` table (canonical decisions)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Create / update
    # ------------------------------------------------------------------

    def save(
        self,
        project: str,
        key: str,
        value: str,
        source_message_id: int | None = None,
        status: str = "draft",
    ) -> dict:
        """Insert or update a decision, preserving uniqueness of (project, key).

        Returns the full stored row as a dict. ``source_message_id`` must
        reference an existing ``chat_messages.id`` unless it is ``None``.
        """
        project = validate_project(project)
        key = validate_key(key)
        value = validate_value(value)
        status = validate_status(status)
        validate_source_message_id(self._conn, project, source_message_id)
        updated_at = utc_now_iso()

        self._conn.execute(
            """
            INSERT INTO project_memory
                (project, key, value, status, source_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (project, key) DO UPDATE SET
                value = excluded.value,
                status = excluded.status,
                source_message_id = excluded.source_message_id,
                updated_at = excluded.updated_at
            """,
            (project, key, value, status, source_message_id, updated_at),
        )
        self._conn.commit()
        return self.get(project, key)

    def update_status(self, project: str, key: str, status: str) -> dict:
        """Change a decision's status without touching its value."""
        project = validate_project(project)
        key = validate_key(key)
        status = validate_status(status)
        cur = self._conn.execute(
            """
            UPDATE project_memory
            SET status = ?, updated_at = ?
            WHERE project = ? AND key = ?
            """,
            (status, utc_now_iso(), project, key),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"decision {project!r}/{key!r} not found")
        self._conn.commit()
        return self.get(project, key)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, project: str, key: str) -> dict:
        """Return one decision as a dict, or raise ``NotFoundError``."""
        project = validate_project(project)
        key = validate_key(key)
        row = self._conn.execute(
            """
            SELECT * FROM project_memory
            WHERE project = ? AND key = ?
            """,
            (project, key),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"decision {project!r}/{key!r} not found")
        return dict(row)

    def list_for_project(
        self,
        project: str,
        *,
        status: str | None = None,
        include_deprecated: bool = True,
    ) -> list[dict]:
        """List a project's decisions, newest first.

        Filters must not widen the query beyond ``project`` — the returned
        rows can only ever come from the given project.
        """
        project = validate_project(project)
        if status is not None:
            status = validate_status(status)
        sql = "SELECT * FROM project_memory WHERE project = ?"
        params: list[object] = [project]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if not include_deprecated:
            sql += " AND status != 'deprecated'"
        sql += " ORDER BY updated_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, project: str, key: str) -> None:
        """Delete one decision; raises ``NotFoundError`` when absent."""
        project = validate_project(project)
        key = validate_key(key)
        cur = self._conn.execute(
            "DELETE FROM project_memory WHERE project = ? AND key = ?",
            (project, key),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"decision {project!r}/{key!r} not found")
        self._conn.commit()


def save_decision(
    project: str,
    key: str,
    value: str,
    source_message_id: int | None = None,
    status: str = "draft",
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> dict:
    """Save or update a canonical decision (team contract signature).

    Uses the default database when no ``conn`` is supplied.
    """
    if conn is None:
        from orbit.database.engine import connect

        conn = connect(db_path)
    return DecisionRepository(conn).save(
        project, key, value, source_message_id, status
    )
