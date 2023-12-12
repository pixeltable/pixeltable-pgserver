SHELL := /bin/bash
PREFIX := $(shell pwd)/../src/pgserver/pginstall/
BUILD := $(shell pwd)/pgbuild/

.PHONY: all
all: pgvector postgres

### postgres
POSTGRES_VERSION := 15.5
POSTGRES_URL := https://ftp.postgresql.org/pub/source/v$(POSTGRES_VERSION)/postgresql-$(POSTGRES_VERSION).tar.gz
POSTGRES_DIR := postgresql-$(POSTGRES_VERSION)

$(POSTGRES_DIR).tar.gz:
	curl -L -O $(POSTGRES_URL)

$(POSTGRES_DIR): $(POSTGRES_DIR).tar.gz
	tar xzf $(POSTGRES_DIR).tar.gz
	touch $(POSTGRES_DIR)

$(PREFIX):
	mkdir -p $(PREFIX)

#https://stackoverflow.com/questions/68379786/
#for explanation of unsetting make env variables prior to calling postgres' own make
$(PREFIX)/bin/postgres: $(POSTGRES_DIR) $(PREFIX)
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && cd $(POSTGRES_DIR) \
		&& ./configure --prefix=$(PREFIX) --without-readline \
		&& $(MAKE) -j \
		&& $(MAKE) install

.PHONY: postgres
postgres: $(PREFIX)/bin/postgres

### pgvector
PGVECTOR_TAG := v0.5.1
PGVECTOR_URL := https://github.com/pgvector/pgvector/archive/refs/tags/$(PGVECTOR_TAG).tar.gz
PGVECTOR_DIR := pgvector-$(PGVECTOR_TAG)

$(PGVECTOR_DIR).tar.gz:
	curl -L -o $(PGVECTOR_DIR).tar.gz $(PGVECTOR_URL)

$(PGVECTOR_DIR): $(PGVECTOR_DIR).tar.gz
	# tar extract into pgvector-$(PGVECTOR_TAG)
	mkdir -p $(PGVECTOR_DIR)
	tar xzf $(PGVECTOR_DIR).tar.gz -C $(PGVECTOR_DIR) --strip-components=1
	touch $(PGVECTOR_DIR)

$(PREFIX)/lib/vector.so: $(PGVECTOR_DIR) $(PREFIX)/bin/postgres
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && cd $(PGVECTOR_DIR) \
		&& export PG_CONFIG=$(PREFIX)/bin/pg_config \
		&& $(MAKE) -j \
		&& $(MAKE) install

.PHONY: pgvector
pgvector: postgres $(PREFIX)/lib/vector.so

### other
.PHONY: clean clean-all
clean:
	rm -rf $(PREFIX)
	rm -rf $(POSTGRES_DIR)
	rm -rf $(PGVECTOR_DIR)

clean-all: clean
	rm -rf *.tar.gz