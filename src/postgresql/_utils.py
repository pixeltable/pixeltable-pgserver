from pathlib import Path
from tempfile import mkdtemp
from ._commands import initdb, pg_ctl, psql
from typing import Optional
import shutil
import atexit
from subprocess import CalledProcessError
import fasteners
import json
import os
import abc

__all__ = ['PostgresServer']

class PostgresServer(abc.ABC):
    """ Abstract base class for postgresql server instances.
        Provides a common interface for interacting with the server.
    """
    def __init__(self, pgdata : Path):
        """ Initializes the postgresql server instance.
            Not intended to be called directly, use get_temporary() or get_shared() instead.
        """

        self.pgdata = pgdata
        self.log = self.pgdata / 'log'
        self.socket_dir = self.pgdata
        self.user = "postgres"

        atexit.register(self._shutdown)
        self._startup()

    @abc.abstractmethod
    def _startup(self) -> None:
        """ Starts the postgresql server and registers the teardown handler. """
        pass

    @abc.abstractmethod
    def _shutdown(self) -> None:
        """ Cleans up. Must be idempotent."""
        pass

    def get_connection_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.user

        return f"postgresql://{self.user}:@/{database}?host={self.socket_dir}"

    def run_psql_command(self, sql : str) -> str:
        """ Runs a psql command on the server and returns the output.
        """
        return psql(f"-d {self.get_connection_uri()} -c '{sql}'")
        
    def get_status(self) -> str:
        """ Returns the status of the postgresql server.
        """
        return pg_ctl(f"-D {self.pgdata} status")
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._shutdown()
        atexit.unregister(self._shutdown)

    @classmethod
    def get_temporary(cls, dir: Optional[Path] = None) -> 'PostgresServer':
        """ Returns a temporary postgresql server instance.
        """
        return TemporaryPostgres(dir)
    
    @classmethod
    def get_instance(cls, pgdata : Path) -> 'PostgresServer':
        """ Returns the postgresql server instance
            for the given pgdata directory. 
            If the corresponding server is not running, it will be started.
            If the pgdata directory does not exist, it will be created.

            The server will remain running until the process exits.            
        """
        return SharedPostgres(pgdata)


class TemporaryPostgres(PostgresServer):
    """
        Temporary postgresql server instance which can be used
        as context manager.
        Listens on unix-domain socket to avoid port conflicts.
        cleanup of server and data can be managed via:

        1) context manager interface
        2) manual call to teardown()
        3) atexit handler if neither of the above are used

        NOTE: at the moment the server and data directory will not be automatically 
        removed if the process is killed with SIGKILL or SIGTERM (see atexit doc)
        
        Args:
            dir: base directory within which temporary pgdata directory will be created.
                The path must already exist and
                the path's file system must allow file locking.
    """
    def __init__(self, dir: Optional[Path] = None):
        pgdata = Path(mkdtemp(dir=dir))
        super().__init__(pgdata)

    def _startup(self) -> None:
        """ Starts the postgresql server and registers the teardown handler. """
        initdb(f"-D {self.pgdata} --auth=trust --auth-local=trust --no-sync -U {self.user}")
        pg_ctl(f'-D {self.pgdata} -w -o "-k {self.socket_dir} -h \\"\\"" -l {self.log} start')

    def _shutdown(self) -> None:
        """ Stops the postgresql server and removes the pgdata directory. """
        try:
            pg_ctl(f"-D {self.pgdata} -m immediate stop")
        except CalledProcessError: 
            pass

        if self.pgdata.exists():
            shutil.rmtree(str(self.pgdata))

class SharedPostgres(PostgresServer):
    """ Represents a local postgres instance where the pgdata is not temporary 
        and may be shared by different clients.

        If the pgdata directory does not exist, it will be created.
        If the server is not running, it will be started.
        If the pgdata directory exists, it will be used as-is.

        Uses refcounts to determine when to stop the server process.
        If this is the last process using the database, the server process will be stopped on teardown(),
    """
    def __init__(self, pgdata : Path):
        self.lock_file = self.pgdata / 'connection.lock'
        self.refcount = self.pgdata / 'refcount'
        self.lock = fasteners.InterProcessLock(self.lock_file)

        super().__init__(pgdata)
        
    def _startup(self) -> None:
        with self.lock:
            # lock will create the directory if it doesn't exist
            # so we need to check specifically for some pgdata files
            self._add_self_pid()

            if not (self.pgdata / 'PG_VERSION').exists():
                initdb(f"-D {self.pgdata} --auth=trust --auth-local=trust -U {self.user}")

            started = False
            try: 
                self.get_status()
                started = True
            except CalledProcessError:
                pass

            if not started:            
                pg_ctl(f'-D {self.pgdata} -w -o "-k {self.socket_dir} -h \\"\\"" -l {self.log} start')

            self.get_status() # check that server is running

    def _shutdown(self) -> None:
        with self.lock:
            pids = self._remove_self_pid()
            if len(pids) == 0: # last process using the database
                try:
                    pg_ctl(f"-D {self.pgdata} stop")
                except CalledProcessError:
                    pass # in case the server was already stopped

    def _add_self_pid(self) -> None:
        if not self.refcount.exists():
            pids = [os.getpid()]
        else:
            pids = json.loads(self.refcount.read_text())
            
        assert os.getpid() not in pids, "adding same pid twice"
        pids.append(os.getpid())
        self.refcount.write_text(json.dumps(pids))

    def _remove_self_pid(self) -> list[int]:
        pids = json.loads(self.refcount.read_text())
        if os.getpid() not in pids:
            # already removed, eg by repeated calls to teardown()
            return pids
        
        pids.remove(os.getpid())
        self.refcount.write_text(json.dumps(pids))
        return pids
    

        



