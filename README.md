![Python Version](https://img.shields.io/badge/python-3.9%2C%203.10%2C%203.11%2C%203.12-blue)
![Postrgres Version](https://img.shields.io/badge/PostgreSQL-16.2-blue)
![Linux Supported](https://img.shields.io/badge/Linux-supported-green)
![macOS Supported](https://img.shields.io/badge/macOS-supported-green)
![Windows Supported](https://img.shields.io/badge/Windows-supported-green)

[![CI](https://github.com/orm011/pgserver/actions/workflows/wheels.yml/badge.svg)](https://github.com/orm011/pgserver/actions)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pgserver)

<p align="center">
  <img src="https://raw.githubusercontent.com/orm011/pgserver/main/pgserver_square_small.png"/>
</p>

# `pgserver`: pip-installable postgres + pgvector for your python app

`pip install pgserver`

`pgserver` lets you build Postgres-backed python apps that remain wholly pip-installable; saving you and your users from needing to understand how to install and setup a postgres server.
To achieve this, you need two things which `pgserver` provides
  * wheels with postgres binaries included
  * convenient initialization and server process management, with defaults so as to not interfere with existing postgres installations, and with handling or prevention of many corner cases (being root, port conflicts, etc)

Additionally, this package includes the `pgvector` extension.

## Basic summary:
* _Pip installable binaries_: built and tested on Manylinux, MacOS and Windows.
* _No sudo or admin rights needed_: Does not require `root` privileges or `sudo`.
* but... _can handle root_: in some environments your python app runs as root, eg some docker containers and google collab, `pgserver` handles this case.
* _Simpler initialization_: `pgserver.get_server(MY_DATA_DIR)` method to initialize data and server if needed, so you don't need to understand `initdb`, `pg_ctl`, port conflicts.
* _Convenient cleanup_: server process cleanup is done for you: when the process using pgserver ends, the server is shutdown, including when multiple independent processes call
`pgserver.get_server(MY_DATA_DIR)` on the same dir (wait for last one)
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
3. includes `pgvector` extension but excludes `postGIS` (need to build cross platform, pull requests taken)
