from __future__ import annotations

import pytest

from qpg.db_pg import PostgresDependencyError, connect_pg
from qpg.schema.privilege_check import check_privileges


@pytest.mark.integration
def test_select_only_role_passes(integration_dsns: dict[str, str]) -> None:
    try:
        with connect_pg(integration_dsns["readonly"]) as conn:
            report = check_privileges(conn)
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))

    assert report.passed is True


@pytest.mark.integration
def test_role_with_insert_privilege_fails(integration_dsns: dict[str, str]) -> None:
    try:
        with connect_pg(integration_dsns["writer"]) as conn:
            report = check_privileges(conn)
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))

    assert report.passed is False
    assert any(v.privilege in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"} for v in report.violations)


@pytest.mark.integration
def test_writer_role_cannot_write_when_qpg_enforces_readonly(
    integration_dsns: dict[str, str],
) -> None:
    try:
        with connect_pg(integration_dsns["writer"]) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT has_table_privilege(
                    current_user,
                    'public.qpg_harness_orders',
                    'INSERT'
                ) AS can_insert
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert bool(row["can_insert"]) is True

            with pytest.raises(Exception, match=r"read-only|ReadOnly|25006"):
                cur.execute(
                    "INSERT INTO public.qpg_harness_orders(status) VALUES ('should_fail')",
                )
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))
