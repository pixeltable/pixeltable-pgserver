import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from ._commands import initdb, pg_ctl
from typing import Optional

__all__ = ["pg_setup", "pg_teardown", "tmp_postgres"]

def pg_setup(user: Optional[str] = "postgres") -> Path:
    pgdata = Path(TemporaryDirectory())
    log = pgdata / 'log'
    initdb(f"-D {pgdata.name} --auth-local=trust --no-sync -U postgres")
    pg_ctl(f'-D {pgdata.name} -w -o "-k {pgdata.name} -h \\"\\"" -l {log} start')
    con_str = f"host={pgdata.name} user={user}"
    return pgdata, con_str

def pg_teardown(pgdata : Path):
    msg = pg_ctl(f"-D {pgdata.name} stop")
    pgdata.cleanup()
    return msg

@pytest.fixture
def tmp_postgres():
    pgdata, con_str = pg_setup()
    yield pgdata, con_str
    pg_teardown(pgdata)

