import pytest
from postgresql import PostgresServer
import subprocess
import tempfile


def _check_server_works(pg : PostgresServer) -> int:
    assert pg.pgdata.exists()
    pid = pg.get_pid()
    assert pid is not None
    ret = pg.psql("select version();")
    assert ret.startswith("PostgreSQL")
    return pid

def _server_is_running(pid : int) -> bool:
    assert pid is not None
    try: 
        subprocess.run(["kill", "-0", str(pid)], check=True)
        return True
    except subprocess.CalledProcessError:
        pass
    return False

def _kill_server(pid : int) -> None:
    if pid is not None:
        subprocess.run(["kill", "-9", str(pid)], check=False)

def test_cleanup_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with PostgresServer.get_server(tmpdir.name) as pg:
                pid = _check_server_works(pg)

            assert not _server_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)

def test_cleanup_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with PostgresServer.get_server(tmpdir.name, cleanup_mode='delete') as pg:
                pid = _check_server_works(pg)

            assert not _server_is_running(pid)
            assert not pg.pgdata.exists()
        finally:
            _kill_server(pid)

def test_cleanup_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with PostgresServer.get_server(tmpdir.name, cleanup_mode=None) as pg:
                pid = _check_server_works(pg)

            assert _server_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)

@pytest.fixture
def tmp_postgres():
    tmp_pg_data = tempfile.mkdtemp()
    with PostgresServer.get_server(tmp_pg_data, cleanup_mode='delete') as pg:
        yield pg

def test_pgvector(tmp_postgres):
    ret = tmp_postgres.run_psql_command("CREATE EXTENSION vector;")
    assert ret == "CREATE EXTENSION\n"
