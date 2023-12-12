# pgserver

Lets you create and use a postrgres server with your python app as easily as you would
sqlite.

Can also be used for self-contained testing against postgres.

A fully self-contained, pip installable,
Python wheel for Linux and MacOS (incl. apple silicon and x86) 
containing a complete, self-contained Postgres server + pgvector
one can embed in a python application.

* Pip installable. Tested on ubuntu and mac (apple silicon + x86), including pgvector extension.
* Does not require `root` or `sudo`.
* Databases can be initialized in any directory
* Wrappers to all binaries, such as `initdb`, `pg_ctl`, `psql`, `pg_config`, for low level control.
* Convenient start: `get_server` factory method to initialize and start server, so you dont need to understand `initdb`, `pg_ctl`, worry about port conflicts, or spend time debugging why you cannot connect.
* Convenient cleanup: manages server process cleanup including when server is shared by independent user processes.
* Context manager protocol.
* Includes header files in case you wish to locally build some other extension against it.

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




