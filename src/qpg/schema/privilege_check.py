from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qpg.db_pg import fetch_all, fetch_one

ROLE_TREE_CTE = """
WITH RECURSIVE role_tree AS (
    SELECT oid AS role_oid, rolname
    FROM pg_roles
    WHERE rolname = current_user
    UNION
    SELECT m.roleid AS role_oid, r.rolname
    FROM role_tree rt
    JOIN pg_auth_members m ON m.member = rt.role_oid
    JOIN pg_roles r ON r.oid = m.roleid
)
"""


@dataclass(frozen=True)
class PrivilegeViolation:
    role: str
    scope: str
    object_name: str
    privilege: str


@dataclass
class PrivilegeReport:
    current_user: str
    inherited_roles: list[str]
    violations: list[PrivilegeViolation]

    @property
    def passed(self) -> bool:
        return not self.violations


def _rows_to_violations(rows: list[dict[str, Any]]) -> list[PrivilegeViolation]:
    violations: list[PrivilegeViolation] = []
    for row in rows:
        violations.append(
            PrivilegeViolation(
                role=str(row["role_name"]),
                scope=str(row["scope"]),
                object_name=str(row["object_name"]),
                privilege=str(row["privilege"]),
            )
        )
    return violations


def build_report_from_rows(
    *,
    current_user: str,
    inherited_roles: list[str],
    violation_rows: list[dict[str, Any]],
) -> PrivilegeReport:
    return PrivilegeReport(
        current_user=current_user,
        inherited_roles=inherited_roles,
        violations=_rows_to_violations(violation_rows),
    )


def collect_prohibited_privileges(conn: Any, *, allow_execute: bool = False) -> list[dict[str, Any]]:
    sql_chunks = [
        """
        SELECT rt.rolname AS role_name,
               'database' AS scope,
               current_database() AS object_name,
               p.privilege AS privilege
        FROM role_tree rt
        CROSS JOIN (VALUES ('CREATE'), ('TEMP')) AS p(privilege)
        WHERE has_database_privilege(rt.rolname, current_database(), p.privilege)
        """,
        """
        SELECT rt.rolname AS role_name,
               'database' AS scope,
               current_database() AS object_name,
               'ALTER/DROP' AS privilege
        FROM role_tree rt
        JOIN pg_roles r ON r.rolname = rt.rolname
        JOIN pg_database d ON d.datname = current_database()
        WHERE d.datdba = r.oid
        """,
        """
        SELECT rt.rolname AS role_name,
               'schema' AS scope,
               n.nspname AS object_name,
               'CREATE' AS privilege
        FROM role_tree rt
        JOIN pg_namespace n ON n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        WHERE has_schema_privilege(rt.rolname, n.oid, 'CREATE')
        """,
        """
        SELECT rt.rolname AS role_name,
               'schema' AS scope,
               n.nspname AS object_name,
               'ALTER/DROP' AS privilege
        FROM role_tree rt
        JOIN pg_roles r ON r.rolname = rt.rolname
        JOIN pg_namespace n ON n.nspowner = r.oid
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        """,
        """
        SELECT rt.rolname AS role_name,
               'table' AS scope,
               n.nspname || '.' || c.relname AS object_name,
               p.privilege AS privilege
        FROM role_tree rt
        JOIN pg_class c ON c.relkind IN ('r', 'p', 'v', 'm', 'f')
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege)
        WHERE n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
          AND has_table_privilege(rt.rolname, c.oid, p.privilege)
        """,
        """
        SELECT rt.rolname AS role_name,
               'table' AS scope,
               n.nspname || '.' || c.relname AS object_name,
               'ALTER/DROP' AS privilege
        FROM role_tree rt
        JOIN pg_roles r ON r.rolname = rt.rolname
        JOIN pg_class c ON c.relowner = r.oid AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        """,
    ]

    if not allow_execute:
        sql_chunks.append(
            """
            SELECT rt.rolname AS role_name,
                   'function' AS scope,
                   n.nspname || '.' || p.proname AS object_name,
                   'EXECUTE' AS privilege
            FROM role_tree rt
            JOIN pg_proc p ON true
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'
              AND has_function_privilege(rt.rolname, p.oid, 'EXECUTE')
            """
        )

    union_sql = (
        f"{ROLE_TREE_CTE}\n"
        + " UNION ALL ".join(sql_chunks)
        + " ORDER BY role_name, scope, object_name, privilege"
    )
    return fetch_all(conn, union_sql)


def list_inherited_roles(conn: Any) -> list[str]:
    rows = fetch_all(
        conn,
        f"""
        {ROLE_TREE_CTE}
        SELECT DISTINCT rolname
        FROM role_tree
        ORDER BY rolname
        """,
    )
    return [str(row["rolname"]) for row in rows]


def check_privileges(conn: Any, *, allow_execute: bool = False) -> PrivilegeReport:
    current = fetch_one(conn, "SELECT current_user AS username")
    current_user = str(current["username"]) if current else "unknown"
    roles = list_inherited_roles(conn)
    rows = collect_prohibited_privileges(conn, allow_execute=allow_execute)
    return build_report_from_rows(
        current_user=current_user,
        inherited_roles=roles,
        violation_rows=rows,
    )


def format_privilege_report(report: PrivilegeReport) -> str:
    lines: list[str] = []
    lines.append(f"Current user: {report.current_user}")
    lines.append(f"Inherited roles: {', '.join(report.inherited_roles) if report.inherited_roles else '(none)'}")

    if report.passed:
        lines.append("Result: PASS (no prohibited privileges detected)")
        return "\n".join(lines)

    lines.append("Result: FAIL (prohibited privileges detected)")
    lines.append("Violations:")
    for violation in report.violations:
        lines.append(
            f"- role={violation.role} scope={violation.scope} object={violation.object_name} privilege={violation.privilege}"
        )
    return "\n".join(lines)
