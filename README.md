# `pgserver`: pip installable self-contained postgres server 

`pip install pgserver`

`pgserver` lets you create and manage a Postgres within your Python app, with server binaries included.
Wheels are built for multiple platforms.

### Example use cases:
* Building a Postgres-backed yet still self-contained Python app, much like you would with `sqlite`.
* Developing and testing apps that depend on some external Postgres (as a dev dependency)

### Basic summary:
* *Pip installable binaries*: tested on Ubuntu and MacOS (apple silicon + x86), including pgvector extension.
* *No sudo needed*: Does not require `root` or `sudo`.
* *Convenient startup*: `pgserver.get_server(MY_DATA_DIR)` factory method to initialize data and server if needed, so you don't need to understand `initdb`, `pg_ctl`, port conflicts, and skip debugging why you still cannot connect to the server.
* *Convenient cleanup*: server process cleanup is done for you, including when multiple independent processes call
`pgserver.get_server(MY_DATA_DIR)`
* Context manager protocol to explicitly control cleanup timing in testing scenarios.
* For lower-level control, wrappers to all binaries, such as `initdb`, `pg_ctl`, `psql`, `pg_config`. Includes header files in case you wish to build some other extension and use it against these binaries.

```py
# Example 1: postgres backed application
import pgserver

pgdata = f'{MY_APP_DIR}/pgdata'
db = pgserver.get_server(pgdata)
# server ready for connection.

print(db.psql('create extension vector'))
db_uri = db.get_uri()
# use uri with sqlalchemy / psycopg, etc

# if no other process is using this server, it will be shutdown at exit,
# if other process use same pgadata, server process will be shutdown when all stop.
```

```py
# Example 2: Testing
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

Based on https://github.com/michelp/postgresql-wheel, with the following differences:
1. Wheels for multiple platforms (MacOS)
2. Server management (initialization and cleanup in a multi-process scenario)
3. pgvector extension included

