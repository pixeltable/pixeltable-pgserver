import pytest
from pathlib import Path
from tempfile import mkdtemp, TemporaryDirectory
from ._commands import initdb, pg_ctl
from typing import Optional
import shutil

__all__ = ["pg_setup", "pg_teardown", "tmp_postgres"]

def pg_setup(dir : Optional[Path] = None, user: Optional[str] = "postgres") -> Path:
    """
        Create a temporary postgresql instance
        Args:
            dir: directory where the temporary pgdata instance will be created
            user: user for the postgresql instance
    """
    pgdata = Path(mkdtemp(dir=dir))
    log = pgdata / 'log'
    initdb(f"-D {pgdata} --auth=trust --auth-local=trust --no-sync -U postgres")
    pg_ctl(f'-D {pgdata} -w -o "-k {pgdata} -h \\"\\"" -l {log} start')
    con_str = f"host={pgdata} user={user}"
    return pgdata, con_str

def pg_teardown(pgdata : Path):
    msg = pg_ctl(f"-D {pgdata} stop")
    shutil.rmtree(str(pgdata))
    return msg

@pytest.fixture
def tmp_postgres():
    pgdata, con_str = pg_setup()
    yield pgdata, con_str
    pg_teardown(pgdata)