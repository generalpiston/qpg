from qpg.schema.privilege_check import build_report_from_rows


def test_privilege_report_passes_without_violations() -> None:
    report = build_report_from_rows(
        current_user="readonly",
        inherited_roles=["readonly"],
        violation_rows=[],
    )

    assert report.passed is True
    assert report.violations == []


def test_privilege_report_fails_with_violation_rows() -> None:
    report = build_report_from_rows(
        current_user="readonly",
        inherited_roles=["readonly", "writer"],
        violation_rows=[
            {
                "role_name": "writer",
                "scope": "table",
                "object_name": "public.orders",
                "privilege": "INSERT",
            }
        ],
    )

    assert report.passed is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.role == "writer"
    assert violation.scope == "table"
    assert violation.object_name == "public.orders"
    assert violation.privilege == "INSERT"
