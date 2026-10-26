import logging
import multiprocessing as mp
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import suppress
from multiprocessing import queues
from pathlib import Path
from typing import Iterator

import psutil
import pytest
import sqlalchemy as sa
from sqlalchemy_utils import create_database, database_exists

from pixeltable_pgserver import PostgresServer, get_server, postgres_server
from pixeltable_pgserver.pgexec import pgexec
from pixeltable_pgserver.utils import PostmasterInfo, find_suitable_port, process_is_running


def _check_sqlalchemy_works(srv: PostgresServer, driver: str | None = None) -> None:
    database_name = 'testdb'
    uri = srv.get_uri(database_name, driver)

    if not database_exists(uri):
        create_database(uri)

    engine = sa.create_engine(uri)
    conn = engine.connect()

    table_name = 'table_foo'
    with conn.begin():
        # if table exists already, drop it
        if engine.dialect.has_table(conn, table_name):
            conn.execute(sa.text(f'drop table {table_name};'))
        conn.execute(sa.text(f'create table {table_name} (id int);'))
        conn.execute(sa.text(f'insert into {table_name} values (1);'))
        cur = conn.execute(sa.text(f'select * from {table_name};'))
        result = cur.fetchone()
        assert result
        assert result[0] == 1


def _check_time_zones(srv: PostgresServer) -> None:
    # Check that time zone information was properly compiled
    database_name = 'testdb'
    uri = srv.get_uri(database_name, 'psycopg')

    if not database_exists(uri):
        create_database(uri)

    engine = sa.create_engine(uri)
    conn = engine.connect()

    with conn.begin():
        conn.execute(sa.text("SET TIME ZONE 'America/Anchorage';"))


def _check_postmaster_info(pgdata: Path, postmaster_info: PostmasterInfo) -> None:
    assert postmaster_info is not None
    assert postmaster_info.pgdata is not None
    assert postmaster_info.pgdata == pgdata

    assert postmaster_info.is_running()

    if postmaster_info.socket_dir is not None:
        assert postmaster_info.socket_dir.exists()
        assert postmaster_info.socket_path is not None
        assert postmaster_info.socket_path.exists()
        assert postmaster_info.socket_path.is_socket()


def _check_server(pg: PostgresServer) -> int:
    assert pg.pgdata.exists()
    postmaster_info = PostmasterInfo.read_from_pgdata(pg.pgdata)
    assert postmaster_info is not None
    assert postmaster_info.pid is not None
    _check_postmaster_info(pg.pgdata, postmaster_info)

    ret = pg.psql('show data_directory;')
    # parse second row (first two are headers)
    ret_path = Path(ret.splitlines()[2].strip())
    assert pg.pgdata == ret_path
    _check_sqlalchemy_works(pg, 'psycopg')  # Use psycopg3 driver
    _check_time_zones(pg)
    return postmaster_info.pid


def _kill_server(pid: int | psutil.Process | None) -> None:
    if pid is None:
        return
    elif isinstance(pid, psutil.Process):
        proc = pid
    else:
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

    if proc.is_running():
        proc.terminate()  # attempt cleaner shutdown
        try:
            proc.wait(3)  # wait at most a few seconds
        except psutil.TimeoutExpired:
            pass

        if proc.is_running():
            proc.kill()


def test_get_port() -> None:
    address = '127.0.0.1'
    port = find_suitable_port(address)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        sock.bind((address, port))
    except OSError as err:
        if 'Address already in use' in str(err):
            raise RuntimeError(f'Port {port} is already in use.') from err
        raise
    finally:
        sock.close()


def test_get_server() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            # check case when initializing the pgdata dir
            with get_server(tmpdir) as pg:
                pid = _check_server(pg)
                assert pg.log.parent == pg.pgdata.parent
                assert pg.log.exists()

            assert not process_is_running(pid)
            assert pg.pgdata.exists()

            # check case when pgdata dir is already initialized
            with get_server(tmpdir) as pg:
                pid = _check_server(pg)

            assert not process_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)


def test_reentrant() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir) as pg:
                pid = _check_server(pg)
                with get_server(tmpdir) as pg2:
                    assert pg2 is pg
                    _check_server(pg)

                _check_server(pg)

            assert not process_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)


def _start_server_in_separate_process(
    pgdata: Path, queue_in: queues.Queue | None, queue_out: queues.Queue, cleanup_mode: str | None
) -> None:
    with get_server(pgdata, cleanup_mode=cleanup_mode) as pg:
        pid = _check_server(pg)
        queue_out.put(pid)

        if queue_in is not None:
            _ = queue_in.get()  # wait for signal
            return


def test_unix_domain_socket() -> None:
    if platform.system() == 'Windows':
        pytest.skip('This test is for unix domain sockets, which are not available on Windows.')

    long_prefix = '_'.join(['long'] + ['1234567890'] * 12)
    assert len(long_prefix) > 120
    prefixes = ['short', long_prefix]

    for prefix in prefixes:
        with tempfile.TemporaryDirectory(dir='/tmp/', prefix=prefix) as tmpdir:
            pid = None
            try:
                with get_server(tmpdir) as pg:
                    pid = _check_server(pg)

                assert not process_is_running(pid)
                assert pg.pgdata.exists()
                if len(prefix) > 120:
                    assert str(tmpdir) not in pg.get_uri()
                else:
                    assert str(tmpdir) in pg.get_uri()
            finally:
                _kill_server(pid)


def test_pg_ctl() -> None:
    if platform.system() != 'Windows' and os.geteuid() == 0:
        # on Linux root, this test would fail.
        # we'd need to create a user etc to run the command, which is not worth it
        # pixeltable_pgserver does this internally, but not worth it for this test
        pytest.skip('This test is not run as root on Linux.')

    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir) as pg:
                output = pgexec('pg_ctl', ('-D', str(pg.pgdata), 'status'), bin_path=pg.bin_path)
                assert 'server is running' in output.splitlines()[0]

        finally:
            _kill_server(pid)


def test_stale_postmaster() -> None:
    """To simulate a stale postmaster.pid file, we create a postmaster.pid file by starting a server,
    back the file up, then restore the backup to the original location after killing the server.
    ( our method to kill the server is graceful to avoid running out of shmem, but this seems to also
        remove the postmaster.pid file, so we need to go to these lengths to simulate a stale postmaster.pid file )
    """
    if platform.system() != 'Windows' and os.geteuid() == 0:
        # on Linux as root, this test fails bc of permissions for the postmaster.pid file
        # we simply skip it in this case, as in practice, the permissions issue would not occur
        pytest.skip('This test is not run as root on Linux.')

    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        pid2 = None

        try:
            with get_server(tmpdir, cleanup_mode='stop') as pg:
                pid = _check_server(pg)
                pgdata = pg.pgdata
                postmaster_pid = pgdata / 'postmaster.pid'

                # make a backup of the postmaster.pid file
                shutil.copy2(str(postmaster_pid), str(postmaster_pid) + '.bak')

            # restore the backup to gurantee a stale postmaster.pid file
            shutil.copy2(str(postmaster_pid) + '.bak', str(postmaster_pid))
            with get_server(tmpdir) as pg:
                pid2 = _check_server(pg)
        finally:
            _kill_server(pid)
            _kill_server(pid2)


def test_stale_postmaster_reused_pid() -> None:
    """After a crash, the pid in a stale postmaster.pid can belong to an unrelated live process: Windows reuses pids
    quickly, and pids start over in a restarted container. The server must still start.
    """
    if platform.system() != 'Windows' and os.geteuid() == 0:
        pytest.skip('This test is not run as root on Linux.')

    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        pid2 = None
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
        try:
            with get_server(tmpdir, cleanup_mode='stop') as pg:
                pid = _check_server(pg)
                postmaster_pid = pg.pgdata / 'postmaster.pid'
                lines = postmaster_pid.read_text().splitlines()

            lines[0] = str(unrelated.pid)
            postmaster_pid.write_text('\n'.join(lines) + '\n')
            with get_server(tmpdir) as pg:
                pid2 = _check_server(pg)
        finally:
            unrelated.kill()
            _kill_server(pid)
            _kill_server(pid2)


def test_stale_postmaster_pid_of_other_server() -> None:
    """The pid in a stale postmaster.pid can also belong to another cluster's postgres, which must be left alone."""
    if platform.system() != 'Windows' and os.geteuid() == 0:
        pytest.skip('This test is not run as root on Linux.')

    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other_tmpdir:
        pid = None
        pid2 = None
        other_pid = None
        try:
            with get_server(other_tmpdir, cleanup_mode=None) as other:
                other_pid = _check_server(other)
            with get_server(tmpdir, cleanup_mode='stop') as pg:
                pid = _check_server(pg)
                postmaster_pid = pg.pgdata / 'postmaster.pid'
                lines = postmaster_pid.read_text().splitlines()

            lines[0] = str(other_pid)
            postmaster_pid.write_text('\n'.join(lines) + '\n')
            with get_server(tmpdir) as pg:
                pid2 = _check_server(pg)
            assert process_is_running(other_pid)
        finally:
            _kill_server(pid)
            _kill_server(pid2)
            _kill_server(other_pid)


def test_uninspectable_server_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """A running server whose command line can't be inspected is still taken as this server, and its
    postmaster.pid stays: postgres shuts down a server whose lock file is gone.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir, cleanup_mode=None) as pg:
                pid = _check_server(pg)

            def access_denied(self: psutil.Process) -> list[str]:
                raise psutil.AccessDenied(self.pid)

            monkeypatch.setattr(psutil.Process, 'cmdline', access_denied)
            with get_server(tmpdir, cleanup_mode=None) as pg:
                assert _check_server(pg) == pid
        finally:
            _kill_server(pid)


def test_wait_for_ready_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A running server that never becomes ready fails the start instead of blocking it, and every other
    pgserver process waiting on the lock, forever.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir, cleanup_mode=None) as pg:
                pid = _check_server(pg)
                postmaster_pid = pg.pgdata / 'postmaster.pid'
                lines = postmaster_pid.read_text().splitlines()

            lines[7] = 'starting'
            postmaster_pid.write_text('\n'.join(lines) + '\n')
            monkeypatch.setattr(postgres_server, '_START_TIMEOUT_SECS', 2)
            with pytest.raises(RuntimeError, match='not ready'):
                get_server(tmpdir, cleanup_mode=None)
        finally:
            _kill_server(pid)


@pytest.mark.parametrize('num_lines', [0, 3])
def test_truncated_postmaster_pid(num_lines: int) -> None:
    """Postgres writes postmaster.pid a few lines at a time during startup, so a crash during startup can leave it
    empty or truncated. The server must still start.
    """
    if platform.system() != 'Windows' and os.geteuid() == 0:
        pytest.skip('This test is not run as root on Linux.')

    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        pid2 = None
        try:
            with get_server(tmpdir, cleanup_mode='stop') as pg:
                pid = _check_server(pg)
                postmaster_pid = pg.pgdata / 'postmaster.pid'
                lines = postmaster_pid.read_text().splitlines()

            postmaster_pid.write_text(''.join(f'{line}\n' for line in lines[:num_lines]))
            with get_server(tmpdir) as pg:
                pid2 = _check_server(pg)
        finally:
            _kill_server(pid)
            _kill_server(pid2)


def test_restart_after_crash() -> None:
    """Kills the server without warning, as a crash or a container teardown does. The next start runs crash recovery,
    which must finish in time; on Windows it used to stall on the server log while that lived inside pgdata.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        pid2 = None
        try:
            with get_server(tmpdir, cleanup_mode=None) as pg:
                pid = _check_server(pg)

            postmaster = psutil.Process(pid)
            procs = [postmaster, *postmaster.children(recursive=True)]
            for proc in procs:
                # once the postmaster is gone, its children may exit before they are killed
                with suppress(psutil.NoSuchProcess):
                    proc.kill()
            psutil.wait_procs(procs, timeout=30)

            with get_server(tmpdir) as pg:
                pid2 = _check_server(pg)
        finally:
            _kill_server(pid)
            _kill_server(pid2)


def test_cleanup_delete() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir, cleanup_mode='delete') as pg:
                pid = _check_server(pg)

            assert not process_is_running(pid)
            assert not pg.pgdata.exists()
            assert not pg.log.exists()
        finally:
            _kill_server(pid)


def test_cleanup_none() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pid = None
        try:
            with get_server(tmpdir, cleanup_mode=None) as pg:
                pid = _check_server(pg)

            assert process_is_running(pid)
            assert pg.pgdata.exists()
        finally:
            _kill_server(pid)


@pytest.fixture
def tmp_postgres() -> Iterator[PostgresServer]:
    tmp_pg_data = tempfile.mkdtemp()
    with get_server(tmp_pg_data, cleanup_mode='delete') as pg:
        yield pg


def test_pgvector(tmp_postgres: PostgresServer) -> None:
    ret = tmp_postgres.psql('CREATE EXTENSION vector;')
    assert ret.strip() == 'CREATE EXTENSION'


def test_start_failure_log(caplog: pytest.LogCaptureFixture) -> None:
    """Test server log contents are shown in python log when failures"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with get_server(tmpdir) as _:
            pass

        # now delete some files to make it fail
        for f in Path(tmpdir).glob('**/postgresql.conf'):
            f.unlink()

        with pytest.raises(subprocess.CalledProcessError):
            _ = get_server(tmpdir)

        assert 'postgres: could not access the server configuration file' in caplog.text


def test_no_conflict() -> None:
    """test we can start pixeltable_pgservers on two different datadirs with no conflict (eg port conflict)"""
    pid1 = None
    pid2 = None
    try:
        with (
            tempfile.TemporaryDirectory() as tmpdir1,
            tempfile.TemporaryDirectory() as tmpdir2,
            get_server(tmpdir1) as pg1,
            get_server(tmpdir2) as pg2,
        ):
            pid1 = _check_server(pg1)
            pid2 = _check_server(pg2)
    finally:
        _kill_server(pid1)
        _kill_server(pid2)


def _reuse_deleted_datadir(prefix: str) -> None:
    """test common scenario where we repeatedly delete the datadir and start a new server on it"""
    """ NB: currently this test is not reproducing the problem """
    # one can reproduce the problem by running the following in a loop:
    #
    # python -c 'import pixeltable as pxt; pxt.Client()'
    # rm -rf ~/.pixeltable/
    # python -c 'import pixeltable as pxt; pxt.Client()'
    #
    # which creates a database with more contents etc
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    pgdata = Path(tmpdir) / 'pgdata'
    server_processes = []
    shmem_ids = []

    num_tries = 3
    try:
        for _ in range(num_tries):
            assert not pgdata.exists()

            queue_from_child: queues.Queue = mp.Queue()
            child = mp.Process(target=_start_server_in_separate_process, args=(pgdata, None, queue_from_child, None))
            child.start()
            # wait for child to start server
            curr_pid = queue_from_child.get()
            child.join()
            server_proc = psutil.Process(curr_pid)
            assert server_proc.is_running()
            server_processes.append(server_proc)
            postmaster = PostmasterInfo.read_from_pgdata(pgdata)
            assert postmaster is not None
            if postmaster.shmget_id is not None:
                shmem_ids.append(postmaster.shmget_id)

            if platform.system() == 'Windows':
                # windows will not allow deletion of the directory while the server is running
                _kill_server(server_proc)

            shutil.rmtree(pgdata)
    finally:
        if platform.system() != 'Windows':
            # if sysv_ipc is installed (eg locally), remove the shared memory segment
            # done this way because of CI/CD issues with sysv_ipc
            # this avoids having to restart the machine to clear the shared memory
            try:
                import sysv_ipc  # type: ignore[import-not-found]

                do_shmem_cleanup = True
            except ImportError:
                do_shmem_cleanup = False
                logging.warning('sysv_ipc not installed, skipping shared memory cleanup...')

            if do_shmem_cleanup:
                for shmid in shmem_ids:
                    try:
                        sysv_ipc.remove_shared_memory(shmid)
                    except sysv_ipc.ExistentialError as e:
                        logging.info(f'shared memory already removed: {e}')

        for proc in server_processes:
            _kill_server(proc)

    shutil.rmtree(tmpdir)


def test_reuse_deleted_datadir_short() -> None:
    """test that new server starts normally on same datadir after datadir is deleted"""
    _reuse_deleted_datadir('short_prefix')


def test_reuse_deleted_datadir_long() -> None:
    """test that new server starts normally on same datadir after datadir is deleted"""
    long_prefix = '_'.join(['long_prefix'] + ['1234567890'] * 12)
    assert len(long_prefix) > 120
    _reuse_deleted_datadir(long_prefix)


def test_multiprocess_shared() -> None:
    """Test that multiple processes can share the same server.

    1. get server in a child process,
    2. then, get server in the parent process
    3. then, exiting the child process
    4. checking the parent can still use the server.
    """
    pid = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_to_child: queues.Queue = mp.Queue()
            queue_from_child: queues.Queue = mp.Queue()
            child = mp.Process(
                target=_start_server_in_separate_process, args=(tmpdir, queue_to_child, queue_from_child, 'stop')
            )
            child.start()
            # wait for child to start server
            server_pid_child = queue_from_child.get()

            with get_server(tmpdir) as pg:
                server_pid_parent = _check_server(pg)
                assert server_pid_child == server_pid_parent

                # tell child to continue
                queue_to_child.put(None)
                child.join()

                # check server still works
                _check_server(pg)

            assert not process_is_running(server_pid_parent)
    finally:
        _kill_server(pid)
