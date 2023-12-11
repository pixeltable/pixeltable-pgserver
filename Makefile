.PHONY: all
all:
	mkdir -p src/postgresql/pgbuild
	cp src/postgresql/Makefile src/postgresql/pgbuild
	cd src/postgresql/pgbuild && $(MAKE)

clean:
	rm -rf build/ wheelhouse/
	rm -rf src/postgresql/{pgbuild,pginstall}
