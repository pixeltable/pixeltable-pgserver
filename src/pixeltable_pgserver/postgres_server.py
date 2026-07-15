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
    POSTGRES_VERSIONS,
    TARGET_POSTGRES_VERSION,
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

# initdb locale for brand-new clusters. The builtin C.UTF-8 provider (PG17+) defines collate
# and ctype itself, so they are identical and platform-independent. This avoids Windows'
# refusal of databases whose collate != ctype, which PG18's libc locale detection can produce
# when no locale is specified (PG16 happened to derive matching values). New clusters always
# use TARGET_POSTGRES_VERSION (>=18), so the builtin provider is guaranteed available.
_NEW_CLUSTER_INITDB_LOCALE_ARGS: tuple[str, ...] = ('--locale-provider=builtin', '--builtin-locale=C.UTF-8')


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

    bin_path: Path

    def __init__(
        self, pgdata: Path, *, cleanup_mode: str | None = 'stop', postgres_version: int = TARGET_POSTGRES_VERSION
    ) -> None:
        """Initializes the postgresql server instance.
        Constructor is intended to be called directly, use get_server() instead.
        """
        assert cleanup_mode in (None, 'stop', 'delete')

        self.bin_path = POSTGRES_VERSIONS.get(postgres_version)
        if self.bin_path is None:
            raise ValueError(f'Unsupported postgres version: {postgres_version}')

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

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        if self._postmaster_info is None:
            return

        assert self._postmaster_info.process is not None
        if not self._postmaster_info.process.is_running():
            return

        try:
            pgexec(
                'pg_ctl',
                ('-w', '-D', str(self.pgdata), 'stop'),
                bin_path=self.bin_path,
                user=self.system_user,
            )
            return
        except subprocess.CalledProcessError:
            pass

        _logger.warning('Failed to stop server; killing it instead.')
        self._postmaster_info.process.terminate()
        try:
            self._postmaster_info.process.wait(2)
        except psutil.TimeoutExpired:
            pass
        if self._postmaster_info.process.is_running():
            self._postmaster_info.process.kill()

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

    def ensure_pgdata_inited(self, *, initdb_locale_args: tuple[str, ...] = _NEW_CLUSTER_INITDB_LOCALE_ARGS) -> None:
        """Initializes the pgdata directory if it is not already initialized."""
        if platform.system() != 'Windows' and os.geteuid() == 0:
            import pwd
            import stat

            assert self.system_user is not None
            ensure_prefix_permissions(self.pgdata)

            read_perm = stat.S_IRGRP | stat.S_IROTH
            execute_perm = stat.S_IXGRP | stat.S_IXOTH
            for path in POSTGRES_VERSIONS.values():
                ensure_prefix_permissions(path)
                # for envs like cibuildwheel docker, where the user has no permissions otherwise
                ensure_folder_permissions(path, execute_perm | read_perm)
                ensure_folder_permissions(path.parent / 'lib', read_perm)

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
                    *initdb_locale_args,
                    '-U',
                    self.postgres_user,
                    '-D',
                    str(self.pgdata),
                ),
                bin_path=self.bin_path,
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
                pgexec(
                    'pg_ctl',
                    pg_ctl_args,
                    bin_path=self.bin_path,
                    user=self.system_user,
                    timeout=10,
                    **subprocess_kwargs,
                )

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
            self._stop()

            if self.cleanup_mode == 'stop':
                return

            assert self.cleanup_mode == 'delete'
            shutil.rmtree(str(self.pgdata))
            atexit.unregister(self._cleanup)

    def psql(self, command: str) -> str:
        """Runs a psql command on this server. The command is passed to psql via stdin."""
        executable = POSTGRES_VERSIONS[TARGET_POSTGRES_VERSION] / 'psql'
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


def get_server(
    pgdata: Path | str,
    *,
    cleanup_mode: str | None = 'stop',
    start: bool = True,
    postgres_version: int = TARGET_POSTGRES_VERSION,
) -> PostgresServer:
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

    version = pgdata_version(pgdata)
    if version is not None and version != postgres_version:
        raise RuntimeError(
            f'Version mismatch: expecting version {postgres_version} but found version {version}: {pgdata}'
        )

    if pgdata in PostgresServer._instances:
        return PostgresServer._instances[pgdata]

    pgdata.mkdir(parents=False, exist_ok=True)

    server = PostgresServer(pgdata, cleanup_mode=cleanup_mode, postgres_version=postgres_version)
    if start:
        server.start()
    return server


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


def _read_template0_locale(pgdata: Path, *, bin_path: Path, user: str | None) -> dict[str, str]:
    """Reads template0's locale settings from a *stopped* cluster via single-user mode.

    pg_upgrade requires the new cluster to be initialized with the same locale as the old one,
    but pg_controldata does not expose locale and the values live in the pg_database catalog. We
    therefore query the catalog offline with `postgres --single`, which needs neither a running
    server, a TCP port, nor the process lock (avoiding the non-reentrant `_lock`). Returns a dict
    with keys datcollate, datctype, encoding, datlocprovider.
    """
    sql = (
        'SELECT datcollate, datctype, pg_encoding_to_char(encoding) AS encoding, datlocprovider '
        "FROM pg_database WHERE datname = 'template0';"
    )
    output = pgexec('postgres', ('--single', '-D', str(pgdata), 'postgres'), bin_path=bin_path, user=user, input=sql)
    fields = dict(re.findall(r'\b(\w+) = "([^"]*)"', output))
    missing = {'datcollate', 'datctype', 'encoding', 'datlocprovider'} - fields.keys()
    if missing:
        raise RuntimeError(f'Could not read locale of {pgdata} (missing {sorted(missing)}). Backend output:\n{output}')
    return fields


def _matching_initdb_locale_args(locale: dict[str, str]) -> tuple[str, ...]:
    """Builds initdb locale args that reproduce `locale` (read from an old cluster) so pg_upgrade
    accepts the new cluster. Existing pgserver clusters use the libc provider; new ones use builtin.
    ICU is never produced by pgserver and is unsupported here."""
    provider = locale['datlocprovider']
    if provider == 'c':  # libc
        return ('--locale-provider=libc', f'--lc-collate={locale["datcollate"]}', f'--lc-ctype={locale["datctype"]}')
    if provider == 'b':  # builtin: a single locale name, stored identically in datcollate/datctype
        return ('--locale-provider=builtin', f'--builtin-locale={locale["datcollate"]}')
    raise RuntimeError(f'Cannot replicate locale provider {provider!r} for upgrade (supported: libc, builtin): {locale}')


def upgrade_db(pgdata: Path | str) -> None:
    """Upgrades the given pgdata directory to the latest version of postgres."""
    if isinstance(pgdata, str):
        pgdata = Path(pgdata)
    pgdata = pgdata.expanduser().resolve()

    target_version = TARGET_POSTGRES_VERSION
    current_version = pgdata_version(pgdata)
    if current_version is None or current_version == target_version:
        # Nothing to do
        return

    assert current_version in POSTGRES_VERSIONS, (
        'Unexpectedly encountered a pgdata folder with a version of postgres that was never supported.'
    )

    _logger.info('Upgrading pgdata from version %s to %s: %s', current_version, target_version, pgdata)

    old_server = get_server(pgdata, start=False, postgres_version=current_version)
    with old_server._lock:
        postmaster_info = PostmasterInfo.read_from_pgdata(pgdata)
        if postmaster_info is not None and postmaster_info.is_running():
            _logger.info('Stopping existing pgserver: %s', postmaster_info)
            pgexec('pg_ctl', ('-D', str(pgdata), 'stop'), bin_path=old_server.bin_path, user=old_server.system_user)

        # The new (target) cluster must be initialized with the same locale as the old cluster, or
        # pg_upgrade will reject the mismatch. The old cluster was created without a pinned locale
        # (it inherited the host OS locale), so read its actual settings from the now-stopped cluster.
        old_locale = _read_template0_locale(pgdata, bin_path=old_server.bin_path, user=old_server.system_user)
        assert old_locale['encoding'] == 'UTF8', f'Unexpected non-UTF8 encoding in existing pgdata: {old_locale}'

        # Our postgres 16 pgdata dirs don't have checksums enabled, but postgres 18 has them on by default.
        # We need to do something here; recommended practice is to enable checksums on the old cluster
        # before upgrading.
        control_data = pgexec(
            'pg_controldata', ('-D', str(pgdata)), bin_path=old_server.bin_path, user=old_server.system_user
        )
        match = re.search(r'Data page checksum version:\s*(\d+)', control_data)
        if not match:
            raise RuntimeError('Could not find checksum version in pg_controldata output')
        checksum_version = int(match.group(1))
        if checksum_version == 0:
            _logger.info('Enabling checksums in existing pgdata directory.')
            pgexec(
                'pg_checksums',
                ('-D', str(pgdata), '--enable'),
                bin_path=old_server.bin_path,
                user=old_server.system_user,
            )

    _logger.info('Initializing new pgdata directory for upgrade.')
    tmp_cluster_dir = Path(tempfile.mkdtemp(dir=pgdata.parent, prefix='.pgdata-tmp-'))
    tmp_server = get_server(tmp_cluster_dir, start=False)

    # Reproduce the old cluster's locale so pg_upgrade accepts the new cluster (rather than the
    # builtin C.UTF-8 default used for brand-new clusters).
    tmp_server.ensure_pgdata_inited(initdb_locale_args=_matching_initdb_locale_args(old_locale))

    _logger.info('Running pg_upgrade.')
    # Run the upgarde with the *new* server's `pg_upgrade` binary, pointing to the *old* server with -b
    tmp_cwd = Path(tempfile.mkdtemp())
    pgexec(
        'pg_upgrade',
        (
            '-b',
            str(old_server.bin_path),
            '-d',
            str(pgdata),
            '-D',
            str(tmp_cluster_dir),
            '-U',
            tmp_server.postgres_user,
        ),
        bin_path=POSTGRES_VERSIONS[TARGET_POSTGRES_VERSION],
        user=tmp_server.system_user,
        cwd=tmp_cwd,
    )

    _logger.info('Moving directories into place.')
    pgdata.rename(Path(str(pgdata) + '.old'))
    tmp_cluster_dir.rename(pgdata)

    new_server = get_server(pgdata)
    # Run update_extensions.sql
    update_extensions_file = tmp_cwd / 'update_extensions.sql'
    if update_extensions_file.exists():
        _logger.info(f'Running script: {update_extensions_file}')
        with open(update_extensions_file, encoding='utf-8') as fp:
            sql = fp.read()
            new_server.psql(sql)
    else:
        _logger.info('No update_extensions.sql file found; skipping.')

    _logger.info('pgdata upgrade complete.')
