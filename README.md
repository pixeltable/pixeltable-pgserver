![Python Version](https://img.shields.io/badge/python-3.9%2C%203.10%2C%203.11-blue)
![Linux Supported](https://img.shields.io/badge/Linux-supported-green)
![macOS Supported](https://img.shields.io/badge/macOS-supported-green)
![Windows Supported](https://img.shields.io/badge/Windows-supported-green)

[![CI](https://github.com/orm011/pgserver/actions/workflows/wheels.yml/badge.svg)](https://github.com/orm011/pgserver/actions)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pgserver)

<p align="center">
  <img src="https://raw.githubusercontent.com/orm011/pgserver/v0.0.8/pgserver_square_small.png"/>
</p>

# `pgserver`: pip-installable postgres + pgvector for your python app

`pip install pgserver`

`pgserver` lets you initialize (if needed) and run a Postgres server associated with a data dir within your Python app, with server binaries included.
Wheels are built for multiple platforms.

### Example use cases:
* The main motivation is to enable building Postgres-backed python apps that remain pip-installable, saving you and, more importantly, your users any need to install and setup postgres.
* The second advantage is avoid remembering how to set-up a local postgres server, instead you immediately get a sqlalchemy or psql usable URI string and get to work.
* Also possible: developing and testing apps that depend on some external Postgres (as a dev dependency)

### Basic summary:
* _Pip installable binaries_: built and tested on Ubuntu and MacOS (apple silicon + x86) and Windows 
* _No sudo needed_: Does not require `root` or `sudo`.
* _Simpler initialization_: `pgserver.get_server(MY_DATA_DIR)` method to initialize data and server if needed, so you don't need to understand `initdb`, `pg_ctl`, port conflicts, and skip debugging why you still cannot connect to the server, just do `server.get_uri()` to connect. Uses unix domain sockets to avoid port conflicts.
* _Convenient cleanup_: server process cleanup is done for you: when the process using pgserver ends, the server is shutdown, including when multiple independent processes call
`pgserver.get_server(MY_DATA_DIR)` on the same dir (wait for last one)
    * includes context manager protocol to explicitly control cleanup timing in testing scenarios.
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

Based on https://github.com/michelp/postgresql-wheel, but with the following differences:
1. binary wheels for multiple platforms (ubuntu x86, MacOS apple silicon, MacOS x86, Windows)
2. postgres server management: cross platform startup and cleanup
3. includes `pgvector` but excludes `postGIS` (need to build cross platform, pull requests taken)
