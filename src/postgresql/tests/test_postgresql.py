import postgresql
from postgresql.testing import pg_setup, pg_teardown, tmp_postgres

def test_setup_teardown():
    pgdata, conn = pg_setup()
    pg_teardown(pgdata)

def test_fixture(tmp_postgres):
    pgdata, con_str = tmp_postgres
    postgresql.psql(f'-d "{con_str}" -c "select version()"')

def test_pgvector_extension(tmp_postgres):
    pgdata, con_str = tmp_postgres
    postgresql.psql(f'-d "{con_str}" -c "CREATE EXTENSION vector;"')