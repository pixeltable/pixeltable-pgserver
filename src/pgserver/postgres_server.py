from pathlib import Path
from typing import Optional, Dict, Union
import shutil
import atexit
import subprocess
import os
import logging
import platform

from ._commands import POSTGRES_BIN_PATH, initdb, pg_ctl
from .utils import find_suitable_port, find_suitable_socket_dir, DiskList, PostmasterInfo, process_is_running

if platform.system() != 'Windows':
    from .utils import ensure_user_exists, ensure_prefix_permissions

class PostgresServer:
    """ Provides a common interface for interacting with a server.
    """
    import platformdirs
    import fasteners

    _instances : Dict[Path, 'PostgresServer'] = {}

    # NB home does not always support locking, eg NFS or LUSTRE (eg some clusters)
    # so, use user_runtime_path instead, which seems to be in a local filesystem
    runtime_path : Path = platformdirs.user_runtime_path('python_PostgresServer')
    lock_path = platformdirs.user_runtime_path('python_PostgresServer') / '.lockfile'
    _lock  = fasteners.InterProcessLock(lock_path)

    def __init__(self, pgdata : Path, *, cleanup_mode : Optional[str] = 'stop'):
        """ Initializes the postgresql server instance.
            Constructor is intended to be called directly, use get_server() instead.
        """
        assert cleanup_mode in [None, 'stop', 'delete']

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

        self.postgres_user = "postgres"
        list_path = self.pgdata / '.handle_pids.json'
        self.global_process_id_list = DiskList(list_path)
        self.cleanup_mode = cleanup_mode
        self._postmaster_info : Optional[PostmasterInfo] = None
        self._count = 0

        atexit.register(self._cleanup)
        with self._lock:
            self._instances[self.pgdata] = self
            self.ensure_pgdata_inited()
            self.ensure_postgres_running()
            self.global_process_id_list.get_and_add(os.getpid())

    def get_postmaster_info(self) -> PostmasterInfo:
        assert self._postmaster_info is not None
        return self._postmaster_info

    def get_pid(self) -> Optional[int]:
        """ Returns the pid of the postgresql server process.
            (First line of postmaster.pid file).
            If the server is not running, returns None.
        """
        return self.get_postmaster_info().pid

    def get_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.postgres_user

        info  = self.get_postmaster_info()
        if info.socket_dir is not None:
            return f"postgresql://{self.postgres_user}:@/{database}?host={info.socket_dir}"
        else:
            assert info.port is not None
            assert info.hostname is not None
            return f"postgresql://{self.postgres_user}:@{info.hostname}:{info.port}/{database}"

    def ensure_pgdata_inited(self) -> None:
        """ Initializes the pgdata directory if it is not already initialized.
        """
        if platform.system() != 'Windows' and os.geteuid() == 0:
            import pwd
            assert self.system_user is not None
            ensure_prefix_permissions(self.pgdata)
            os.chown(self.pgdata, pwd.getpwnam(self.system_user).pw_uid,
                        pwd.getpwnam(self.system_user).pw_gid)

        if not (self.pgdata / 'PG_VERSION').exists():
            initdb(['--auth=trust', '--auth-local=trust', '--encoding=utf8', '-U', self.postgres_user], pgdata=self.pgdata,
                    user=self.system_user)

    def ensure_postgres_running(self) -> None:
        """ pre condition: pgdata is initialized
            post condition: self._postmaster_info is set.
        """
        self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
        if self._postmaster_info is None:
            if platform.system() != 'Windows':
                # use sockets to avoid any future conflict with port numbers
                socket_dir = find_suitable_socket_dir(self.pgdata, self.runtime_path)

                if self.system_user is not None and socket_dir != self.pgdata:
                    ensure_prefix_permissions(socket_dir)
                    socket_dir.chmod(0o777)

                pg_ctl_args = ['-w',  # wait for server to start
                        '-o', '-h ""',  # no listening on any IP addresses (forwarded to postgres exec) see man postgres for -hj
                        '-o',  f'-k {socket_dir}', # socket option (forwarded to postgres exec) see man postgres for -k
                        '-l', str(self.log), # log location: set to pgdata dir also
                        'start' # action
                ]
            else: # Windows,
                # socket.AF_UNIX is undefined when running on Windows, so default to a port
                host = "127.0.0.1"
                port = find_suitable_port(host)
                pg_ctl_args = ['-w',  # wait for server to start
                        '-o', f'-h "{host}"',
                        '-o', f'-p {port}',
                        '-l', str(self.log), # log location: set to pgdata dir also
                        'start' # action
                ]

            try:
                pg_ctl(pg_ctl_args,pgdata=self.pgdata, user=self.system_user, timeout=10)
            except subprocess.CalledProcessError as err:
                logging.error(f"Failed to start server.\nShowing contents of postgres server log ({self.log.absolute()}) below:\n{self.log.read_text()}")
                raise err
            except subprocess.TimeoutExpired as err:
                logging.error(f"Timeout starting server.\nShowing contents of postgres server log ({self.log.absolute()}) below:\n{self.log.read_text()}")
                raise err

        self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
        assert self._postmaster_info is not None
        assert self._postmaster_info.pid is not None

    def _cleanup(self) -> None:
        with self._lock:
            pids = self.global_process_id_list.get_and_remove(os.getpid())

            if pids != [os.getpid()]: # includes case where already cleaned up
                return
            # last handle is being removed
            del self._instances[self.pgdata]
            if self.cleanup_mode is None: # done
                return

            assert self.cleanup_mode in ['stop', 'delete']
            if process_is_running(self._postmaster_info.pid):
                try:
                    pg_ctl(['-w', 'stop'], pgdata=self.pgdata, user=self.system_user)
                except subprocess.CalledProcessError:
                    pass # somehow the server is already stopped.

            if self.cleanup_mode == 'stop':
                return

            assert self.cleanup_mode == 'delete'
            shutil.rmtree(str(self.pgdata))
            atexit.unregister(self._cleanup)

    def psql(self, command : str) -> str:
        """ Runs a psql command on this server. The command is passed to psql via stdin.
        """
        executable = POSTGRES_BIN_PATH / 'psql'
        stdout = subprocess.check_output(f'{executable} {self.get_uri()}',
                                         input=command.encode(), shell=True)
        return stdout.decode("utf-8")

    def __enter__(self):
        self._count += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._count -= 1
        if self._count <= 0:
            self._cleanup()

    def cleanup(self) -> None:
        """ Stops the postgresql server and removes the pgdata directory.
        """
        self._cleanup()


def get_server(pgdata : Union[Path,str] , cleanup_mode : Optional[str] = 'stop' ) -> PostgresServer:
    """ Returns handle to postgresql server instance for the given pgdata directory.
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
        raise FileNotFoundError(f"Parent directory of pgdata does not exist: {pgdata.parent}")

    if not pgdata.exists():
        pgdata.mkdir(parents=False, exist_ok=False)

    if pgdata in PostgresServer._instances:
        return PostgresServer._instances[pgdata]

    return PostgresServer(pgdata, cleanup_mode=cleanup_mode)
