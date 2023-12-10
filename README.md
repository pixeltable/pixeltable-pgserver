# postgresql-wheel

Based on https://github.com/michelp/postgresql-wheel.

A Python wheel for Linux and MacOS (incl. apple silicon) 
containing a complete, self-contained Postgres server.

* Postgres 15 at the moment
* Does not require root or sudo.
* Databases can be initialized in any directory.

Postgres binaries in the package can be found in the directory pointed
to by the `postgresql.pg_bin` global variable.  Function wrappers
around all of the postgres binary programs, like `initdb` and `pg_ctl`
functions are provided for convenience:

Convenience class `PostgresServer` includes best-effort cleanup of both processes and 
data directory and context manager interface.
