import pytest
from postgresql import TemporaryPostgres

@pytest.fixture
def tmp_postgres():
    with TemporaryPostgres() as pg:
        yield pg

def test_fixture(tmp_postgres):
    tmp_postgres.run_psql_command("select version();")

def test_pgvector(tmp_postgres):
    ret = tmp_postgres.run_psql_command("CREATE EXTENSION vector;")
    assert ret == "CREATE EXTENSION\n"
