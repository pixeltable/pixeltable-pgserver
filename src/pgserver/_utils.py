from pathlib import Path
from typing import Optional, Dict, Union, List
import shutil
import atexit
import subprocess
import json
import os
import logging
import hashlib
import socket
import platform
import stat

from ._commands import POSTGRES_BIN_PATH, initdb, pg_ctl
from .shared import PostmasterInfo, _process_is_running


if platform.system() != 'Windows':
    import pwd
    def ensure_user_exists(username : str) -> Optional[pwd.struct_passwd]:
        """ Ensure system user `username` exists.
            Returns their pwentry if user exists, otherwise it creates a user through `useradd`.
            Assume permissions to add users, eg run as root.
        """
        try:
            entry = pwd.getpwnam(username)
        except KeyError:
            entry = None

        if entry is None:
            subprocess.run(["useradd", "-s", "/bin/bash", username], check=True, capture_output=True, text=True)
            entry = pwd.getpwnam(username)

        return entry

    def ensure_prefix_permissions(path: Path):
        """ Ensure target user can traverse prefix to path
            Permissions for everyone will be increased to ensure traversal.
        """
        # ensure path exists and user exists
        assert path.exists()
        prefix = path.parent
        # chmod g+rx,o+rx: enable other users to traverse prefix folders
        g_rx_o_rx = stat.S_IRGRP |  stat.S_IROTH | stat.S_IXGRP | stat.S_IXOTH
        while True:
            curr_permissions = prefix.stat().st_mode
            ensure_permissions = curr_permissions | g_rx_o_rx
            # TODO: are symlinks handled ok here?
            prefix.chmod(ensure_permissions)
            if prefix == prefix.parent: # reached file system root
                break
            prefix = prefix.parent

__all__ = ['get_server']

class _DiskList:
    """ A list of integers stored in a file on disk.
    """
    def __init__(self, path : Path):
        self.path = path

    def get_and_add(self, value : int) -> List[int]:
        old_values = self.get()
        values = old_values.copy()
        if value not in values:
            values.append(value)
            self.put(values)
        return old_values

    def get_and_remove(self, value : int) -> List[int]:
        old_values = self.get()
        values = old_values.copy()
        if value in values:
            values.remove(value)
            self.put(values)
        return old_values

    def get(self) -> List[int]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())

    def put(self, values : List[int]) -> None:
        self.path.write_text(json.dumps(values))


def socket_name_length_ok(socket_name : Path):
    ''' checks whether a socket path is too long for domain sockets
        on this system. Returns True if the socket path is ok, False if it is too long.
    '''
    if socket_name.exists():
        return socket_name.is_socket()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(socket_name))
        return True
    except OSError as err:
        if 'AF_UNIX path too long' in str(err):
            return False
        raise err
    finally:
        sock.close()
        socket_name.unlink(missing_ok=True)


class PostgresServer:
    """ Provides a common interface for interacting with a server.
    """
    import platformdirs
    import fasteners

    _instances : Dict[Path, 'PostgresServer'] = {}

    # lockfile for whole class
    # home dir does not always support locking (eg some clusters)
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

        if os.geteuid() == 0 and platform.system() != 'Windows':
            # running as root
            # need a different system user to run as
            self.system_user = 'pgserver'
            ensure_user_exists(self.system_user)

        self.postgres_user = "postgres"
        list_path = self.pgdata / '.handle_pids.json'
        self.global_process_id_list = _DiskList(list_path)
        self.cleanup_mode = cleanup_mode
        self._postmaster_info : Optional[PostmasterInfo] = None
        self._count = 0

        atexit.register(self._cleanup)
        self._init_server()

    def _find_suitable_socket_dir(self) -> Path:
        """ Assumes server is not running. Returns a suitable directory for used with pg_ctl.
            Usually, this is the same directory as the pgdata directory.
            However, if the pgdata directory exceeds the maximum length for domain sockets on this system,
            a different directory will be used.
        """
        # find a suitable directory for the domain socket
        # 1. pgdata. simplest approach, but can be too long for unix socket depending on the path
        # 2. runtime_path. This is a directory that is intended for storing runtime data.

        # for shared folders, use a hash of the path to avoid collisions of different folders
        # use a hash of the pgdata path combined with inode number to avoid collisions
        string_identifier = f'{self.pgdata}-{self.pgdata.stat().st_ino}'
        path_hash = hashlib.sha256(string_identifier.encode()).hexdigest()[:10]

        candidate_socket_dir = [
            self.pgdata,
            self.runtime_path / path_hash,
        ]

        ok_path = None
        for path in candidate_socket_dir:
            path.mkdir(parents=True, exist_ok=True)
            # name used by postgresql for domain socket is .s.PGSQL.5432
            if socket_name_length_ok(path / '.s.PGSQL.5432'):
                ok_path = path
                logging.info(f"Using socket path: {path}")
                break
            else:
                logging.info(f"Socket path too long: {path}. Will try a different directory for socket.")

        if ok_path is None:
            raise RuntimeError("Could not find a suitable socket path")

        return ok_path

    def get_postmaster_info(self) -> PostmasterInfo:
        assert self._postmaster_info is not None
        return self._postmaster_info

    def get_pid(self) -> int:
        """ Returns the pid of the postgresql server process.
            (First line of postmaster.pid file).
            If the server is not running, returns None.
        """
        return self.get_postmaster_info().pid

    def get_socket_dir(self) -> Path:
        """ Returns the directory of the domain socket used by the server.
        """
        return self.get_postmaster_info().socket_dir

    def get_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.postgres_user

        return f"postgresql://{self.postgres_user}:@/{database}?host={self.get_socket_dir()}"

    def _init_server(self) -> None:
        """ Starts the postgresql server and registers the shutdown handler.
            Effect: self._postmaster_info is set.
        """
        with self._lock:
            self._instances[self.pgdata] = self

            if self.system_user is not None and platform.system() != 'Windows':
                ensure_prefix_permissions(self.pgdata)
                os.chown(self.pgdata, pwd.getpwnam(self.system_user).pw_uid,
                        pwd.getpwnam(self.system_user).pw_gid)

            if not (self.pgdata / 'PG_VERSION').exists():
                initdb(['--auth=trust',  '--auth-local=trust',  '-U', self.postgres_user], pgdata=self.pgdata,
                       user=self.system_user)

            self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
            if self._postmaster_info is None:
                socket_dir = self._find_suitable_socket_dir()
                if self.system_user is not None and socket_dir != self.pgdata:
                    ensure_prefix_permissions(socket_dir)
                    socket_dir.chmod(0o777)

                try:
                    # -o to pg_ctl are options to be passed directly to the postgres executable, be wary of quotes (man pg_ctl)
                    pg_ctl(['-w',  # wait for server to start
                            '-o',  f'-k {socket_dir}', # socket option (forwarded to postgres exec) see man postgres for -k
                            '-o', '-h ""',  # no listening on any IP addresses (forwarded to postgres exec) see man postgres for -hj
                            '-l', str(self.log),   # log location: set to pgdata dir also
                            'start' # action
                            ],
                           pgdata=self.pgdata, user=self.system_user)
                except subprocess.CalledProcessError as err:
                    logging.error(f"Failed to start server.\nShowing contents of postgres server log ({self.log.absolute()}) below:\n{self.log.read_text()}")
                    raise err

            self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
            assert self._postmaster_info is not None
            assert self._postmaster_info.pid is not None
            assert self._postmaster_info.socket_dir is not None

            self.global_process_id_list.get_and_add(os.getpid())

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
            if _process_is_running(self._postmaster_info.pid):
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
        prefix must be a valid directory.
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









