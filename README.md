# pgserver

Based on https://github.com/michelp/postgresql-wheel.

A fully self-contained, pip installable,
Python wheel for Linux and MacOS (incl. apple silicon) 
containing a complete, self-contained Postgres server 
one can embed in a python application.

* Postgres 15 at the moment
* Does not require root or sudo.
* Databases can be initialized in any directory
* Wrappers to all binaries `initdb` and `pg_ctl`.
* Higher level convenience handle that abstracts 
    initdb, pg_ctl, and manages server process start and stop, accounting for 
 access from multiple independent processes (via refcounting).

```
# Example 1: 
# postgres backed application
import pgserver

pgdata = f'{MY_APP_DIR}/pgdata'
db = pgserver.get_server(pgdata)
# server ready for connection.
db_uri = db.get_uri()
# use uri with sqlalchemy / etc.

# if no other process is using this server, it will be shutdown at exit,
# if other process use same pgadata, server process will be shutdown when all stop.
sys.exit()



# Example 2:  
# Testing
import tempfile
import pytest
@pytest.fixture
def tmp_postgres():
    tmp_pg_data = tempfile.mkdtemp()
    with pgserver.get_server(tmp_pg_data, cleanup_mode='delete') as pg:
        yield pg

```

Postgres binaries in the package can be found in the directory pointed
to by the `pgserver.pg_bin` global variable. 
