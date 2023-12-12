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
handleA = pgserver.get_server('/path/to/pgdataA') # inits and starts server
uriA = handle.get_uri() # can use with eg, 
```

Postgres binaries in the package can be found in the directory pointed
to by the `pgserver.pg_bin` global variable. 
