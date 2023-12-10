from pathlib import Path
from ._commands import initdb, pg_ctl, pg_bin
from typing import Optional, Dict, Union
import shutil
import atexit
import subprocess
import fasteners
import json
import os
import platformdirs

__all__ = ['PostgresServer']


class DiskList:
    """ A list of integers stored in a file on disk.
    """
    def __init__(self, path : Path):
        self.path = path

    def get_and_add(self, value : int) -> list[int]:
        old_values = self.get()
        values = old_values.copy()
        if value not in values:
            values.append(value)
            self.put(values)
        return old_values
        
    def get_and_remove(self, value : int) -> list[int]:
        old_values = self.get()
        values = old_values.copy()
        if value in values:
            values.remove(value)
            self.put(values)
        return old_values
    
    def get(self) -> list[int]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())
    
    def put(self, values : list[int]) -> None:
        self.path.write_text(json.dumps(values))


class PostgresServer:
    """ Provides a common interface for interacting with a server.
    """
    _instances : Dict[Path, 'PostgresServer'] = {}

    # lockfile for whole class
    # home dir does not always support locking (eg some clusters)
    _lock  = fasteners.InterProcessLock(platformdirs.user_runtime_path('python_PostgresServer') / '.lockfile')

    def __init__(self, pgdata : Path, *, cleanup_mode : Optional[str] = 'stop'):
        """ Initializes the postgresql server instance.
            Not intended to be called directly, use get_server() instead.
        """
        assert cleanup_mode in [None, 'stop', 'delete']

        self.pgdata = pgdata
        self.log = self.pgdata / 'log'
        self.socket_dir = self.pgdata
        self.user = "postgres"
        self.handle_pids = DiskList(self.pgdata / '.handle_pids.json')
        self._postmaster_pid = self.pgdata / 'postmaster.pid'
        self.cleanup_mode = cleanup_mode

        self._count = 0
        atexit.register(self._cleanup)
        self._startup()

    def get_executable_path(self) -> Path:
        """ Returns the path to the postgresql executable.
        """
        return pg_bin

    def get_pid(self) -> Optional[int]:
        """ Returns the pid of the postgresql server process.
            (First line of postmaster.pid file).
            If the server is not running, returns None.
        """
        if not self._postmaster_pid.exists():
            return None
        else:
            return int(self._postmaster_pid.read_text().splitlines()[0])
        
    def get_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.user

        return f"postgresql://{self.user}:@/{database}?host={self.socket_dir}"

    def _startup(self) -> None:
        """ Starts the postgresql server and registers the shutdown handler. """
        with self._lock:
            self._instances[self.pgdata] = self
            
            if not (self.pgdata / 'PG_VERSION').exists():
                initdb(f"-D {self.pgdata} --auth=trust --auth-local=trust -U {self.user}")

            if self.get_pid() is None:            
                pg_ctl(f'-D {self.pgdata} -w -o "-k {self.socket_dir} -h \\"\\"" -l {self.log} start')

            self.handle_pids.get_and_add(os.getpid())
            assert self.get_pid() is not None, "Server failed to start"

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
        stdout = subprocess.check_output(f'{self.get_executable_path() / 'psql'} {self.get_uri()}', 
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

    @classmethod
    def get_server(cls, pgdata : Union[Path,str] , cleanup_mode : Optional[str] = 'stop' ) -> 'PostgresServer':
        """ Returns handle to postgresql server instance for the given pgdata directory. 
        Args:
            pgdata: pddata directory. If the pgdata directory does not exist, it will be created.
            cleanup_mode: If 'stop', the server will be stopped when the last handle is closed (default)
                          If 'delete', the server will be stopped and the pgdata directory will be deleted.
                          If None, the server will not be stopped or deleted.
                          
            To create a truly temporary server, use mkdtemp() to create a temporary directory and pass it as pg_data, 
            and set cleanup_mode to 'delete'.
        """
        if isinstance(pgdata, str):
            pgdata = Path(pgdata)
        pgdata = pgdata.expanduser().resolve()

        if pgdata in cls._instances:
            return cls._instances[pgdata]

        return PostgresServer(pgdata, cleanup_mode=cleanup_mode)



    

        



