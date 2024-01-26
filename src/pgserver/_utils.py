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
import time
from ._commands import initdb, pg_ctl, pg_bin
from .shared import PostmasterInfo, _process_is_running

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
    _lock  = fasteners.InterProcessLock(platformdirs.user_runtime_path('python_PostgresServer') / '.lockfile')


    def __init__(self, pgdata : Path, *, cleanup_mode : Optional[str] = 'stop'):
        """ Initializes the postgresql server instance.
            Constructor is intended to be called directly, use get_server() instead.
        """
        assert cleanup_mode in [None, 'stop', 'delete']

        self.pgdata = pgdata
        self.log = self.pgdata / 'log'
        self.user = "postgres"
        self.handle_pids = _DiskList(self.pgdata / '.handle_pids.json')
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
            database = self.user

        return f"postgresql://{self.user}:@/{database}?host={self.get_socket_dir()}"

    def _init_server(self) -> None:
        """ Starts the postgresql server and registers the shutdown handler.
            Effect: self._postmaster_info is set.
        """
        with self._lock:
            self._instances[self.pgdata] = self
            self.pgdata.mkdir(parents=True, exist_ok=True)

            if not (self.pgdata / 'PG_VERSION').exists():
                initdb(f"-D {self.pgdata} --auth=trust --auth-local=trust -U {self.user}")

            self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
            if self._postmaster_info is None:
                socket_dir = self._find_suitable_socket_dir()
                try:
                    pg_ctl(f'-D {self.pgdata} -w -o "-k {socket_dir} -h \\"\\"" -l {self.log} start')
                except subprocess.CalledProcessError as err:
                    logging.error(f"Failed to start server.\nShowing contents of postgres server log ({self.log.absolute()}) below:\n{self.log.read_text()}")
                    raise err

            self._postmaster_info = PostmasterInfo.read_from_pgdata(self.pgdata)
            assert self._postmaster_info is not None
            assert self._postmaster_info.pid is not None
            assert self._postmaster_info.socket_dir is not None

            self.handle_pids.get_and_add(os.getpid())

    def _cleanup(self) -> None:
        with self._lock:
            pids = self.handle_pids.get_and_remove(os.getpid())

            if pids != [os.getpid()]: # includes case where already cleaned up
                return
            # last handle is being removed
            del self._instances[self.pgdata]
            if self.cleanup_mode is None: # done
                return

            assert self.cleanup_mode in ['stop', 'delete']
            if _process_is_running(self._postmaster_info.pid):
                try:
                    pg_ctl(f"-D {self.pgdata} -w stop")
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
        executable = pg_bin / 'psql'
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
        pgdata: pddata directory. If the pgdata directory does not exist, it will be created.
        cleanup_mode: If 'stop', the server will be stopped when the last handle is closed (default)
                        If 'delete', the server will be stopped and the pgdata directory will be deleted.
                        If None, the server will not be stopped or deleted.

        To create a temporary server, use mkdtemp() to create a temporary directory and pass it as pg_data,
        and set cleanup_mode to 'delete'.
    """
    if isinstance(pgdata, str):
        pgdata = Path(pgdata)
    pgdata = pgdata.expanduser().resolve()

    if pgdata in PostgresServer._instances:
        return PostgresServer._instances[pgdata]

    return PostgresServer(pgdata, cleanup_mode=cleanup_mode)









