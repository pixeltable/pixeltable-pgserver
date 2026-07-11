import atexit
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar

import fasteners  # type: ignore[import-untyped]
import platformdirs
import psutil
from typing_extensions import Self

from .pgexec import pgexec
from .utils import (
    POSTGRES_16_BIN_PATH,
    POSTGRES_BIN_PATH,
    DiskList,
    PostmasterInfo,
    find_suitable_port,
    find_suitable_socket_dir,
)

if platform.system() != 'Windows':
    from .utils import ensure_folder_permissions, ensure_prefix_permissions, ensure_user_exists

_logger = logging.getLogger('pixeltable_pgserver')

# Windows process creation flags
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


class PostgresServer:
    """Provides a common interface for interacting with a server."""

    _instances: ClassVar[dict[Path, 'PostgresServer']] = {}

    runtime_path: Path = platformdirs.user_runtime_path('python_PostgresServer')
    if not runtime_path.exists():
        # On some Linux systems, this directory does not necessarily exist, and there is no obvious way to create it
        # at this time. Fall back on the temporary directory.
        runtime_path = Path(tempfile.gettempdir())
    lock_path = runtime_path / '.lockfile'
    _lock = fasteners.InterProcessLock(lock_path)

    def __init__(self, pgdata: Path, *, cleanup_mode: str | None = 'stop'):
        """Initializes the postgresql server instance.
        Constructor is intended to be called directly, use get_server() instead.
        """
        assert cleanup_mode in (None, 'stop', 'delete')

        self.pgdata = pgdata
        self.log = self.pgdata / 'log'

        # postgres user name, NB not the same as system user name
        self.system_user = None

        # note os.geteuid() is not available on windows, so must go after
        if platform.system() != 'Windows' and os.geteuid() == 0:
            # running as root
            # need a different system user to run as
            self.system_user = 'pgserver'
            ensure_user_exists(self.system_user)

        self.postgres_user = 'postgres'
        list_path = self.pgdata / '.handle_pids.json'
        self.global_process_id_list = DiskList(list_path)
        self.cleanup_mode = cleanup_mode
        self._postmaster_info: PostmasterInfo | None = None
        self._count = 0

    def start(self) -> None:
        atexit.register(self._cleanup)
        with self._lock:
            self._instances[self.pgdata] = self
            self.ensure_pgdata_inited()
            self.ensure_postgres_running()
            self.global_process_id_list.get_and_add(os.getpid())

    def get_postmaster_info(self) -> PostmasterInfo:
        assert self._postmaster_info is not None
        return self._postmaster_info

    def get_pid(self) -> int | None:
        """Returns the pid of the postgresql server process.
        (First line of postmaster.pid file).
        If the server is not running, returns None.
        """
        return self.get_postmaster_info().pid

    def get_uri(self, database: str | None = None, driver: str | None = None) -> str:
        """Returns a connection string for the postgresql server."""
        return self.get_postmaster_info().get_uri(database=database, driver=driver)

    def ensure_pgdata_inited(self) -> None:
        """Initializes the pgdata directory if it is not already initialized."""
        if platform.system() != 'Windows' and os.geteuid() == 0:
            import pwd
            import stat

            assert self.system_user is not None
            ensure_prefix_permissions(self.pgdata)
            ensure_prefix_permissions(POSTGRES_BIN_PATH)
            ensure_prefix_permissions(POSTGRES_16_BIN_PATH)

            read_perm = stat.S_IRGRP | stat.S_IROTH
            execute_perm = stat.S_IXGRP | stat.S_IXOTH
            # for envs like cibuildwheel docker, where the user is has no permission otherwise
            ensure_folder_permissions(POSTGRES_BIN_PATH, execute_perm | read_perm)
            ensure_folder_permissions(POSTGRES_BIN_PATH.parent / 'lib', read_perm)
            ensure_folder_permissions(POSTGRES_16_BIN_PATH, execute_perm | read_perm)
            ensure_folder_permissions(POSTGRES_16_BIN_PATH.parent / 'lib', read_perm)

            os.chown(self.pgdata, pwd.getpwnam(self.system_user).pw_uid, pwd.getpwnam(self.system_user).pw_gid)

        if not (self.pgdata / 'PG_VERSION').exists():  # making a new PGDATA
            # First ensure there are no left-over servers on a previous version of the same pgdata path,
            # which does happen on Mac/Linux if the previous pgdata was deleted without stopping the server process
            # (the old server continues running for some time, sometimes indefinitely)
            #
            # It is likely the old server could also corrupt the data beyond the socket file, so it is best to kill it.
            # This must be done before initdb to ensure no race conditions with the old server.
            #
            # Since we do not know PID information of the old server, we stop all servers with the same pgdata path.
            # way to test this:
            #
            # python -c 'import pixeltable as pxt; pxt.init()'
            # rm -rf ~/.pixeltable/
            # python -c 'import pixeltable as pxt; pxt.init()'
            _logger.info(f'no PG_VERSION file found within {self.pgdata}. Initializing pgdata')
            for proc in psutil.process_iter(attrs=('name', 'cmdline')):
                if (
                    proc.info['name'] == 'postgres'
                    and proc.info['cmdline'] is not None
                    and str(self.pgdata) in proc.info['cmdline']
                ):
                    _logger.info(
                        f'Found a running postgres server with same `pgdata` dir: '
                        f"{proc.as_dict(attrs=('name', 'pid', 'cmdline'))=}."
                        'Assuming it is a leftover from a previous run on a different '
                        'version of the same `pgdata` path; killing it.'
                    )
                    proc.terminate()
                    with suppress(psutil.TimeoutExpired):
                        proc.wait(2)
                    if proc.is_running():
                        proc.kill()
                    assert not proc.is_running()

            pgexec(
                'initdb',
                (
                    '--auth=trust',
                    '--auth-local=trust',
                    '--encoding=utf8',
                    '-U',
                    self.postgres_user,
                    '-D',
                    str(self.pgdata),
                ),
                user=self.system_user,
            )
        else:
            _logger.info('PG_VERSION file found, skipping initdb')

    def ensure_postgres_running(self) -> None:
        """pre condition: pgdata is initialized, being run with lock.
        post condition: self._postmaster_info is set.
        """

        postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
        if postmaster_info is not None and postmaster_info.is_running():
            _logger.info(f'a postgres server is already running: {postmaster_info=} {postmaster_info.process=}')
            self._postmaster_info = postmaster_info
        else:
            if postmaster_info is not None and not postmaster_info.is_running():
                _logger.info(f'found a postmaster.pid file, but the server is not running: {postmaster_info=}')
            if postmaster_info is None:
                _logger.info(f'no postmaster.pid file found in {self.pgdata}')

            postgres_args: str
            subprocess_kwargs: dict[str, Any]

            if platform.system() != 'Windows':
                # use sockets to avoid any future conflict with port numbers
                socket_dir = find_suitable_socket_dir(self.pgdata, self.runtime_path)

                if self.system_user is not None and socket_dir != self.pgdata:
                    ensure_prefix_permissions(socket_dir)
                    socket_dir.chmod(0o777)

                # no listening on any IP addresses (forwarded to postgres exec) see man postgres for -hj
                # socket option (forwarded to postgres exec) see man postgres for -k
                postgres_args = f'-h "" -k {socket_dir}'
                subprocess_kwargs = {}

            else:  # Windows
                socket_dir = None
                # socket.AF_UNIX is undefined when running on Windows, so default to a port
                host = '127.0.0.1'
                port = find_suitable_port(host)
                postgres_args = f'-h "{host}" -p {port}'
                subprocess_kwargs = {
                    'close_fds': True,
                    # Create a new process group to detach postgres from the Python process.
                    # Ensure that the postgres process does not create a new console window.
                    'creationflags': CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                }

            try:
                pg_ctl_args = ('-w', '-o', postgres_args, '-l', str(self.log), '-D', str(self.pgdata), 'start')
                _logger.info(f'running pg_ctl... {pg_ctl_args=}')
                pgexec('pg_ctl', pg_ctl_args, user=self.system_user, timeout=10, **subprocess_kwargs)

            except subprocess.SubprocessError:
                _logger.error(
                    f'Failed to start server.\nShowing contents of postgres server log ({self.log.absolute()}) '
                    f'below:\n{self.log.read_text()}'
                )
                raise

            while True:
                # in Windows, when there is a postmaster.pid,  init_ctl seems to return
                # but the file is not immediately updated, here we wait until the file shows
                # a new running server. see test_stale_postmaster
                _logger.info('Waiting for postmaster info to show a running process.')
                pinfo = PostmasterInfo.read_from_pgdata(self.pgdata)
                _logger.info(f'Running; checking if ready {pinfo=}')
                if pinfo is not None and pinfo.is_running() and pinfo.status == 'ready':
                    self._postmaster_info = pinfo
                    break

                _logger.info('Not ready yet; waiting a bit longer.')
                time.sleep(1.0)

        _logger.info(f'Now asserting server is running {self._postmaster_info=}')
        assert self._postmaster_info is not None
        assert self._postmaster_info.is_running()
        assert self._postmaster_info.status == 'ready'

    def _cleanup(self) -> None:
        with self._lock:
            pids = self.global_process_id_list.get_and_remove(os.getpid())
            _logger.info(f'Exiting {os.getpid()} remaining {pids=}')
            if pids != [os.getpid()]:  # includes case where already cleaned up
                return

            _logger.info(f'Cleaning last handle for server: {self.pgdata}')
            # last handle is being removed
            del self._instances[self.pgdata]
            if self.cleanup_mode is None:  # done
                return

            assert self.cleanup_mode in ('stop', 'delete')
            if self._postmaster_info is not None:
                assert self._postmaster_info.process is not None
                if self._postmaster_info.process.is_running():
                    try:
                        pgexec('pg_ctl', ('-w', '-D', str(self.pgdata), 'stop'), user=self.system_user)
                        stopped = True
                    except subprocess.CalledProcessError:
                        stopped = False
                        pass  # somehow the server is already stopped.

                    if not stopped:
                        _logger.warning('Failed to stop server; killing it instead.')
                        self._postmaster_info.process.terminate()
                        try:
                            self._postmaster_info.process.wait(2)
                        except psutil.TimeoutExpired:
                            pass
                        if self._postmaster_info.process.is_running():
                            self._postmaster_info.process.kill()

            if self.cleanup_mode == 'stop':
                return

            assert self.cleanup_mode == 'delete'
            shutil.rmtree(str(self.pgdata))
            atexit.unregister(self._cleanup)

    def psql(self, command: str) -> str:
        """Runs a psql command on this server. The command is passed to psql via stdin."""
        executable = POSTGRES_BIN_PATH / 'psql'
        stdout = subprocess.check_output(f'{executable} {self.get_uri()}', input=command.encode(), shell=True)
        return stdout.decode('utf-8')

    def __enter__(self) -> Self:
        self._count += 1
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        self._count -= 1
        if self._count <= 0:
            self._cleanup()

    def cleanup(self) -> None:
        """Stops the postgresql server and removes the pgdata directory."""
        self._cleanup()


def get_server(pgdata: Path | str, cleanup_mode: str | None = 'stop', start: bool = True) -> PostgresServer:
    """Returns handle to postgresql server instance for the given pgdata directory.
    Args:
        pgdata: pddata directory. If the pgdata directory does not exist, it will be created, but its
        parent must exists and be a valid directory.
        cleanup_mode: If 'stop', the server will be stopped when the last handle is closed (default)
                        If 'delete', the server will be stopped and the pgdata directory will be deleted.
                        If None, the server will not be stopped or deleted.

        To create a temporary server, use mkdtemp() to create a temporary directory and pass it as pg_data,
        and set cleanup_mode to 'delete'.
    """
    if isinstance(pgdata, str):
        pgdata = Path(pgdata)
    pgdata = pgdata.expanduser().resolve()

    if not pgdata.parent.exists():
        raise FileNotFoundError(f'Parent directory of pgdata does not exist: {pgdata.parent}')

    if not pgdata.exists():
        pgdata.mkdir(parents=False, exist_ok=False)

    if pgdata in PostgresServer._instances:
        return PostgresServer._instances[pgdata]

    server = PostgresServer(pgdata, cleanup_mode=cleanup_mode)
    if start:
        server.start()
    return server


def installed_pg_version() -> int:
    """Returns the installed major version of postgres."""
    full_version = pgexec('postgres', ('--version',)).strip().split()[-1]
    return int(full_version.split('.')[0])


def pgdata_version(pgdata: Path | str) -> int | None:
    """Returns the version of postgres that initialized the given pgdata directory,
    or None if it is not initialized."""
    if isinstance(pgdata, str):
        pgdata = Path(pgdata)
    pgdata = pgdata.expanduser().resolve()

    version_file = pgdata / 'PG_VERSION'
    if not version_file.exists():
        return None

    return int(version_file.read_text().strip())


def upgrade_db(pgdata: Path | str) -> None:
    """Upgrades the given pgdata directory to the installed version of postgres."""
    if isinstance(pgdata, str):
        pgdata = Path(pgdata)
    pgdata = pgdata.expanduser().resolve()

    target_version = installed_pg_version()
    current_version = pgdata_version(pgdata)
    if current_version is None or current_version == target_version:
        # Nothing to do
        return None

    assert current_version == 16, (
        'Unexpectedly encountered a pgdata folder with a version of postgres that was never supported.'
    )

    print('Upgrading pgdata from version %s to %s: %s', current_version, target_version, pgdata)

    old_server = get_server(pgdata, start=False)
    with old_server._lock:
        postmaster_info = PostmasterInfo.read_from_pgdata(pgdata)
        if postmaster_info is not None and postmaster_info.is_running():
            print('Stopping existing pgserver: %s', postmaster_info)
            pgexec('pg_ctl', ('-D', str(pgdata), 'stop'), bin_path=POSTGRES_16_BIN_PATH, user=old_server.system_user)

        # Our postgres 16 pgdata dirs don't have checksums enabled, but postgres 18 has them on by default.
        # We need to do something here; recommended practice is to enable checksums on the old cluster
        # before upgrading.
        control_data = pgexec(
            'pg_controldata', ('-D', str(pgdata)), bin_path=POSTGRES_16_BIN_PATH, user=old_server.system_user
        )
        match = re.search(r'Data page checksum version:\s*(\d+)', control_data)
        if not match:
            raise RuntimeError('Could not find checksum version in pg_controldata output')
        checksum_version = int(match.group(1))
        if checksum_version == 0:
            print('Enabling checksums in existing pgdata directory.')
            pgexec(
                'pg_checksums',
                ('-D', str(pgdata), '--enable'),
                bin_path=POSTGRES_16_BIN_PATH,
                user=old_server.system_user,
            )

    print('Initializing new pgdata directory for upgrade.')
    tmp_cluster_dir = Path(tempfile.mkdtemp())
    tmp_server = get_server(tmp_cluster_dir, start=False)

    tmp_server.ensure_pgdata_inited()

    print('Running pg_upgrade.')
    # Run the upgarde with the *new* server's `pg_upgrade` binary, pointing to the *old* server with -b
    tmp_cwd = Path(tempfile.mkdtemp())
    pgexec(
        'pg_upgrade',
        (
            '-b',
            str(POSTGRES_16_BIN_PATH),
            '-d',
            str(pgdata),
            '-D',
            str(tmp_cluster_dir),
            '-U',
            tmp_server.postgres_user,
        ),
        user=tmp_server.system_user,
        cwd=tmp_cwd,
    )

    print('Moving directories into place.')
    pgdata.rename(Path(str(pgdata) + '.old'))
    tmp_cluster_dir.rename(pgdata)

    new_server = get_server(pgdata)
    # Run update_extensions.sql
    update_extensions_file = tmp_cwd / 'update_extensions.sql'
    print(f'Running script: {update_extensions_file}')
    with open(update_extensions_file, encoding='utf-8') as fp:
        sql = fp.read()
        new_server.psql(sql)

    print('pgdata upgrade complete.')
