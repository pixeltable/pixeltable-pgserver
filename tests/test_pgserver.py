import pytest
import pgserver
import subprocess
import tempfile
from typing import Optional
import multiprocessing as mp


def _check_server_works(pg : 'PostgresServer') -> int:
    assert pg.pgdata.exists()
    pid = pg.get_pid()
    assert pid is not None
    ret = pg.psql("show data_directory;")
    assert str(pg.pgdata) in ret
    return pid

def _server_is_running(pid : int) -> bool:
    assert pid is not None
    try: 
        subprocess.run(["kill", "-0", str(pid)], check=True)
        return True
    except subprocess.CalledProcessError:
        pass
    return False

def _kill_server(pid : Optional[int]) -> None:
    if pid is None:
        return
    subprocess.run(["kill", "-9", str(pid)])

def test_cleanup_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with pgserver.get_server(tmpdir) as pg:
                pid = _check_server_works(pg)

            assert not _server_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)

def test_reentrant():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with pgserver.get_server(tmpdir) as pg:
                pid = _check_server_works(pg)
                with pgserver.get_server(tmpdir) as pg2:
                    assert pg2 is pg
                    _check_server_works(pg)

                _check_server_works(pg)

            assert not _server_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)

def _start_and_wait(tmpdir, queue_in, queue_out):
    with pgserver.get_server(tmpdir) as pg:
        pid = _check_server_works(pg)
        queue_out.put(pid)

        # now wait for parent to tell us to exit
        _ = queue_in.get()

def test_multiprocess_shared():
    """ Test that multiple processes can share the same server
        by getting server in a child process, 
        then getting it again in the parent process.
        then exiting the child process.
        Then checking that the parent can still use the server.
    """
    pid = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_to_child = mp.Queue()
            queue_from_child = mp.Queue()
            child = mp.Process(target=_start_and_wait, args=(tmpdir,queue_to_child,queue_from_child))
            child.start()
            # wait for child to start server
            server_pid_child = queue_from_child.get()

            with pgserver.get_server(tmpdir) as pg:
                server_pid_parent = _check_server_works(pg)
                assert server_pid_child == server_pid_parent

                # tell child to continue
                queue_to_child.put(None)
                child.join()
            
                # check server still works
                _check_server_works(pg)

            assert not _server_is_running(server_pid_parent)
    finally:
        _kill_server(pid)                


def test_cleanup_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with pgserver.get_server(tmpdir, cleanup_mode='delete') as pg:
                pid = _check_server_works(pg)

            assert not _server_is_running(pid)
            assert not pg.pgdata.exists()
        finally:
            _kill_server(pid)

def test_cleanup_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with pgserver.get_server(tmpdir, cleanup_mode=None) as pg:
                pid = _check_server_works(pg)

            assert _server_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)

@pytest.fixture
def tmp_postgres():
    tmp_pg_data = tempfile.mkdtemp()
    with pgserver.get_server(tmp_pg_data, cleanup_mode='delete') as pg:
        yield pg

def test_pgvector(tmp_postgres):
    ret = tmp_postgres.psql("CREATE EXTENSION vector;")
    assert ret == "CREATE EXTENSION\n"
