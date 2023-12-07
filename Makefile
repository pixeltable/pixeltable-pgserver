.PHONY: all
all:
	cd src/postgresql && mkdir -p pgbuild && make -C pgbuild -f ../Makefile

clean:
	rm -rf build
	rm -rf src/postgresql/{pgbuild,pginstall}
	rm -rf wheelhouse/
