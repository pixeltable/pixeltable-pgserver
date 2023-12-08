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
        Temporary postgresql server instance for testing.
        Listens on unix-domain socket to avoid port conflicts.
        Provides context manager for stopping the server and removing the pgdata directory.
        It will also stop the server and remove the pgdata directory when the process ends.
        NOTE: at the moment the server and data directory won't be automatically 
        removed if the process is killed.
        
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
        atexit.register(self.teardown)
        pg_ctl(f'-D {self.pgdata} -w -o "-k {self.socket_dir} -h \\"\\"" -l {self.log} start')

    def teardown(self) -> None:
        """ Stops the postgresql server and removes the pgdata directory. """
        try:
            print('shutting down server')
            pg_ctl(f"-D {self.pgdata} -m immediate stop")
        except CalledProcessError: # may already have stopped, or never started. this is fine.
            print('server already stopped')

        if self.pgdata.exists():
            shutil.rmtree(str(self.pgdata))
        print('done with teardown')
    
    def get_connection_uri(self, database : Optional[str] = None) -> str:
        """ Returns a connection string for the postgresql server.
        """
        if database is None:
            database = self.user

        return f"postgresql://{self.user}:@/{database}?host={self.socket_dir}"

    def run_psql_command(self, sql : str) -> str:
        return psql(f"-d {self.get_connection_uri()} -c '{sql}'")
        
    def get_status(self):
        return pg_ctl(f"-D {self.pgdata} status")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.teardown()


class PostgresInstance:
    """ Represents a local postgres instance where the pgdata is not temporary.
        If the pgdata directory does not exist, it will be created.
        If the server is not running, it will be started.
        If the pgdata directory exists, it will be used as-is.
        If this is the last process using the database, the server process will be stopped.
    """
    def __init__(self, pgdata : Path, ):
        self.user = "postgres"
        self.pgdata = pgdata
        self.log = self.pgdata / 'log'



