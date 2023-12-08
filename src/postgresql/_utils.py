from pathlib import Path
from tempfile import mkdtemp
from ._commands import initdb, pg_ctl, psql
from typing import Optional
import shutil
import atexit
from subprocess import CalledProcessError

__all__ = ["TemporaryPostgres"]

class TemporaryPostgres:
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
        self.pgdata = Path(mkdtemp(dir=dir))
        self.log = self.pgdata / 'log'
        self.user = "postgres"
        self.socket_dir = self.pgdata # for now, we'll use the pgdata directory for the socket

        initdb(f"-D {self.pgdata} --auth=trust --auth-local=trust --no-sync -U {self.user}")
        atexit.register(self._teardown)
        pg_ctl(f'-D {self.pgdata} -w -o "-k {self.socket_dir} -h \\"\\"" -l {self.log} start')

    def _teardown(self) -> None:
        """ Stops the postgresql server and removes the pgdata directory. """
        try:
            pg_ctl(f"-D {self.pgdata} -m immediate stop")
        except CalledProcessError: 
            pass

        if self.pgdata.exists():
            shutil.rmtree(str(self.pgdata))

    def teardown(self) -> None:
        """ Stops the postgresql server and removes the pgdata directory. """
        self._teardown()
        atexit.unregister(self._teardown) # avoid stderror from double cleanup 
    
    def get_connection_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.user

        return f"postgresql://{self.user}:@/{database}?host={self.socket_dir}"

    def run_psql_command(self, sql : str) -> str:
        """ 
            TODO: pass from stdin instead of using -c
        """
        return psql(f"-d {self.get_connection_uri()} -c '{sql}'")
        
    def get_status(self):
        return pg_ctl(f"-D {self.pgdata} status")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._teardown()
        atexit.unregister(self._teardown)


class Postgres:
    """ Represents a local postgres instance where the pgdata is not temporary.
        If the pgdata directory does not exist, it will be created.
        If the server is not running, it will be started.
        If the pgdata directory exists, it will be used as-is.

        Uses refcounts to determine when to stop the server process.
        If this is the last process using the database, the server process will be stopped on teardown(),
        New instances will restart the server.
    """
    def __init__(self, pgdata : Path):
        self.user = "postgres"
        self.pgdata = pgdata
        self.log = self.pgdata / 'log'
        self.socket_dir = self.pgdata




