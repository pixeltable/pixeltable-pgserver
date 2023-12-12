# pgserver

Lets you create and use a postrgres server with your python app as easily as you would
sqlite.

Based on https://github.com/michelp/postgresql-wheel, but distribute 
multi-platform wheels (including macos, apple silicon) 
as well as a convenience class for managing server sharing across processes and server cleanup when sharers are done so 
you dont have multiple ghost postgres processes left.



Can also be used for self-contained testing against postgres.

A fully self-contained, pip installable,
Python wheel for Linux and MacOS (incl. apple silicon) 
containing a complete, self-contained Postgres server 
one can embed in a python application.

* Pip installable.
* Does not require root or sudo.
* Databases can be initialized in any directory
* Wrappers to all binaries `initdb` and `pg_ctl` for low level control.
* Tested on ubuntu and mac (apple silicon + x86)
* Convenience `get_server` making it easy to think of your postgres instance as a shared data_dir.
  manages server process start and stop, accounting for access from multiple independent processes (via refcounting).
* Other: includes pgvector extension. Includes header files in case you wish to locally build some other extension against it.

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
