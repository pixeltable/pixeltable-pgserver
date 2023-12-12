# pgserver

Lets you create and use a postrgres server with your python app as easily as you would
sqlite.

Can also be used for self-contained testing against postgres.

A fully self-contained, pip installable,
Python wheel for Linux and MacOS (incl. apple silicon and x86) 
containing a complete, self-contained Postgres server + pgvector
one can embed in a python application.

* Pip installable.
* Does not require root or sudo.
* Databases can be initialized in any directory
* Wrappers to all binaries `initdb` and `pg_ctl` for low level control.
* Tested on ubuntu and mac (apple silicon + x86)
* Convenience `get_server` making it easy to think of your postgres instance as a shared data_dir.
  manages server process start and stop, accounting for access from multiple independent processes (via refcounting).
* Other: includes pgvector extension. Includes header files in case you wish to locally build some other extension against it.

```py
# Example 1:
pip install pgserver
# postgres backed application
import pgserver

pgdata = f'{MY_APP_DIR}/pgdata'
db = pgserver.get_server(pgdata)
# server ready for connection.

print(db.psql('create extension vector'))
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

Based on https://github.com/michelp/postgresql-wheel, with some differences, eg, multi-platform,
as well as server management for sharing a server across processes.




