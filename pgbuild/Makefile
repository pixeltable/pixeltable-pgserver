SHELL := /bin/bash
INSTALL_RELPATH := ../src/pixeltable_pgserver/pginstall
INSTALL_PREFIX := $(shell pwd)/$(INSTALL_RELPATH)
BUILD := $(shell pwd)/pgbuild/

.PHONY: all
all: pgvector pgvectorscale postgres

### postgres
POSTGRES_VERSION := 16.10
POSTGRES_URL := https://ftp.postgresql.org/pub/source/v$(POSTGRES_VERSION)/postgresql-$(POSTGRES_VERSION).tar.gz
POSTGRES_SRC := postgresql-$(POSTGRES_VERSION)
POSTGRES_BLD := $(POSTGRES_SRC)

$(POSTGRES_SRC).tar.gz:
	curl -L -O $(POSTGRES_URL)

## extract
$(POSTGRES_SRC)/configure: $(POSTGRES_SRC).tar.gz
	tar xzf $(POSTGRES_SRC).tar.gz
	touch $(POSTGRES_SRC)/configure

## configure
$(POSTGRES_BLD)/config.status: $(POSTGRES_SRC)/configure
	mkdir -p $(POSTGRES_BLD)
	cd $(POSTGRES_BLD) && ../$(POSTGRES_SRC)/configure --prefix=$(INSTALL_PREFIX) --without-icu

## build
# https://stackoverflow.com/questions/68379786/
# for explanation of unsetting make env variables prior to calling postgres' own make
$(POSTGRES_BLD)/src/bin/initdb/initdb: $(POSTGRES_BLD)/config.status
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && $(MAKE) -C $(POSTGRES_BLD) -j

## install to INSTALL_PREFIX
# On Windows, the Postgres build (in particular, the `zic` tool) fails to compile the timezone database into its proper
# place. I don't know why this is; no error message is generated, though I suspect it's because the pathname is too
# long, or something of that nature. In any case, we add an additional post-build step to manually compile the timezone
# data using a shorter path reference, ensuring that it gets generated properly on Windows.
$(INSTALL_PREFIX)/bin/postgres: $(POSTGRES_BLD)/config.status
	mkdir -p $(INSTALL_PREFIX)
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && $(MAKE) -C $(POSTGRES_BLD) install
	$(POSTGRES_BLD)/src/timezone/zic -d $(INSTALL_RELPATH)/share/postgresql/timezone $(POSTGRES_BLD)/src/timezone/data/tzdata.zi

.PHONY: postgres
postgres: $(INSTALL_PREFIX)/bin/postgres

### pgvector
PGVECTOR_TAG := v0.8.1
PGVECTOR_URL := https://github.com/pgvector/pgvector/archive/refs/tags/$(PGVECTOR_TAG).tar.gz
PGVECTOR_DIR := pgvector-$(PGVECTOR_TAG)

$(PGVECTOR_DIR).tar.gz:
	curl -L -o $(PGVECTOR_DIR).tar.gz $(PGVECTOR_URL)

$(PGVECTOR_DIR)/Makefile: $(PGVECTOR_DIR).tar.gz
	# tar extract into pgvector-$(PGVECTOR_TAG)
	mkdir -p $(PGVECTOR_DIR)
	tar xzf $(PGVECTOR_DIR).tar.gz -C $(PGVECTOR_DIR) --strip-components=1
	touch $(PGVECTOR_DIR)/Makefile

$(INSTALL_PREFIX)/lib/vector.so: $(PGVECTOR_DIR)/Makefile $(INSTALL_PREFIX)/bin/postgres
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS \
		&& export PG_CONFIG=$(INSTALL_PREFIX)/bin/pg_config \
		&& $(MAKE) -C $(PGVECTOR_DIR) -j \
		&& $(MAKE) -C $(PGVECTOR_DIR) install

.PHONY: pgvector
pgvector: postgres $(INSTALL_PREFIX)/lib/vector.so

### pgvectorscale (Rust-based extension using pgrx)
# Requires: Rust toolchain (rustup), cargo
# Note: Building on macOS x86 (Intel) is not supported upstream
PGVECTORSCALE_TAG := 0.9.0
PGVECTORSCALE_URL := https://github.com/timescale/pgvectorscale/archive/refs/tags/$(PGVECTORSCALE_TAG).tar.gz
PGVECTORSCALE_DIR := pgvectorscale-$(PGVECTORSCALE_TAG)

# Detect if we're on macOS x86 (Intel) where pgvectorscale is not supported
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)
IS_MACOS_X86 := $(shell [ "$(UNAME_S)" = "Darwin" ] && [ "$(UNAME_M)" = "x86_64" ] && echo "yes" || echo "no")

$(PGVECTORSCALE_DIR).tar.gz:
	curl -L -o $(PGVECTORSCALE_DIR).tar.gz $(PGVECTORSCALE_URL)

$(PGVECTORSCALE_DIR)/pgvectorscale/Cargo.toml: $(PGVECTORSCALE_DIR).tar.gz
	mkdir -p $(PGVECTORSCALE_DIR)
	tar xzf $(PGVECTORSCALE_DIR).tar.gz -C $(PGVECTORSCALE_DIR) --strip-components=1
	touch $(PGVECTORSCALE_DIR)/pgvectorscale/Cargo.toml

# Build pgvectorscale using cargo-pgrx
# The extension source is in the pgvectorscale/pgvectorscale subdirectory
# Skip on macOS x86 (Intel) as it's not supported upstream
$(INSTALL_PREFIX)/lib/vectorscale.so: $(PGVECTORSCALE_DIR)/pgvectorscale/Cargo.toml $(INSTALL_PREFIX)/bin/postgres pgvector
ifeq ($(IS_MACOS_X86),yes)
	@echo "WARNING: Skipping pgvectorscale build on macOS x86 (Intel) - not supported upstream"
	@echo "See: https://github.com/timescale/pgvectorscale/issues/155"
else
	@echo "Building pgvectorscale with Rust/pgrx..."
	@command -v cargo >/dev/null 2>&1 || { echo "Error: Rust/cargo not found. Install via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"; exit 1; }
	cd $(PGVECTORSCALE_DIR)/pgvectorscale && \
		PGRX_VERSION=$$(cargo metadata --format-version 1 2>/dev/null | jq -r '.packages[] | select(.name == "pgrx") | .version') && \
		cargo install --locked cargo-pgrx --version $$PGRX_VERSION && \
		cargo pgrx init --pg16 $(INSTALL_PREFIX)/bin/pg_config && \
		cargo pgrx install --pg-config $(INSTALL_PREFIX)/bin/pg_config --release
endif

.PHONY: pgvectorscale
pgvectorscale: pgvector $(INSTALL_PREFIX)/lib/vectorscale.so

### other
.PHONY: clean clean-all
clean:
	rm -rf $(INSTALL_PREFIX)
	rm -rf $(POSTGRES_SRC)
	rm -rf $(POSTGRES_BLD)
	rm -rf $(PGVECTOR_DIR)
	rm -rf $(PGVECTORSCALE_DIR)

clean-all: clean
	rm -rf *.tar.gz
