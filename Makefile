.PHONY: all
all:
	cd src/postgresql && makedir -p pgbuild && make -C pgbuild all