from __future__ import annotations

import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest

COMPOSE_FILE = Path(__file__).parent / "harness" / "docker-compose.yml"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests with local Docker harness",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return

    skip_integration = pytest.mark.skip(reason="integration tests disabled (use --run-integration)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def _docker_compose_cmd(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), *args]


def _run_compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _docker_compose_cmd(*args),
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_compose_available() -> None:
    try:
        probe = _run_compose("version")
    except FileNotFoundError:
        pytest.skip("docker CLI is not available")

    if probe.returncode != 0:
        message = probe.stderr.strip() or probe.stdout.strip() or "docker compose unavailable"
        pytest.skip(message)


def _wait_for_postgres() -> None:
    admin_dsn = "postgresql://postgres:postgres@127.0.0.1:55432/postgres"
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return
        except Exception:
            time.sleep(1)

    pytest.skip("postgres harness did not become ready")


def _provision_roles() -> None:
    admin_dsn = "postgresql://postgres:postgres@127.0.0.1:55432/postgres"
    statements = [
        "DROP ROLE IF EXISTS qpg_ro_user",
        "DROP ROLE IF EXISTS qpg_rw_user",
        "DROP ROLE IF EXISTS qpg_rw_group",
        "CREATE ROLE qpg_ro_user LOGIN PASSWORD 'qpg_ro_user'",
        "CREATE ROLE qpg_rw_user LOGIN PASSWORD 'qpg_rw_user'",
        "CREATE ROLE qpg_rw_group NOLOGIN",
        "GRANT qpg_rw_group TO qpg_rw_user",
        "REVOKE CREATE, TEMP ON DATABASE postgres FROM PUBLIC",
        "REVOKE CREATE, TEMP ON DATABASE postgres FROM qpg_ro_user, qpg_rw_user, qpg_rw_group",
        "CREATE TABLE IF NOT EXISTS public.qpg_harness_orders(id BIGSERIAL PRIMARY KEY, status TEXT)",
        "REVOKE ALL ON TABLE public.qpg_harness_orders FROM qpg_ro_user, qpg_rw_user, qpg_rw_group",
        "GRANT SELECT ON TABLE public.qpg_harness_orders TO qpg_ro_user, qpg_rw_user",
        "GRANT INSERT ON TABLE public.qpg_harness_orders TO qpg_rw_group",
    ]

    with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def _start_harness() -> None:
    up = _run_compose("up", "-d", "--wait")
    if up.returncode != 0:
        fallback = _run_compose("up", "-d")
        if fallback.returncode != 0:
            message = fallback.stderr.strip() or fallback.stdout.strip() or "docker compose up failed"
            pytest.skip(message)


def _stop_harness() -> None:
    _run_compose("down", "-v")


@pytest.fixture(scope="session")
def integration_dsns(request: pytest.FixtureRequest) -> Generator[dict[str, str]]:
    if not request.config.getoption("--run-integration"):
        pytest.skip("integration tests disabled")

    _ensure_compose_available()
    _start_harness()
    _wait_for_postgres()
    _provision_roles()

    dsns = {
        "readonly": "postgresql://qpg_ro_user:qpg_ro_user@127.0.0.1:55432/postgres",
        "writer": "postgresql://qpg_rw_user:qpg_rw_user@127.0.0.1:55432/postgres",
    }

    try:
        yield dsns
    finally:
        _stop_harness()
