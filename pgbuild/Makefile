SHELL := /bin/bash
INSTALL_RELPATH := ../src/pixeltable_pgserver/pginstall
INSTALL_PREFIX := $(shell pwd)/$(INSTALL_RELPATH)
BUILD := $(shell pwd)/pgbuild/

.PHONY: all
all: pgvector postgres icu

### postgres
POSTGRES_VERSION := 16.11
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
# Point postgres at the in-tree ICU build (see icu target below) and embed an
# rpath so installed binaries resolve libicu* from pginstall/lib at runtime.
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
  PG_LDFLAGS := -Wl,-rpath,@loader_path/../lib
else ifeq ($(UNAME_S),Linux)
  PG_LDFLAGS := -Wl,-rpath,\$$ORIGIN/../lib
else
  PG_LDFLAGS :=
endif

$(POSTGRES_BLD)/config.status: $(POSTGRES_SRC)/configure $(INSTALL_PREFIX)/lib/pkgconfig/icu-i18n.pc
	mkdir -p $(POSTGRES_BLD)
	cd $(POSTGRES_BLD) && \
		PKG_CONFIG_PATH=$(INSTALL_PREFIX)/lib/pkgconfig \
		LDFLAGS="$(PG_LDFLAGS)" \
		../$(POSTGRES_SRC)/configure --prefix=$(INSTALL_PREFIX) --with-icu

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

### icu
# Built from source into $(INSTALL_PREFIX) so the wheel is self-contained.
# On macOS we rewrite the dylibs' install_names to @rpath/... after install so
# downstream binaries (postgres, pgvector) that link against them pick up a
# relocatable reference instead of the absolute $(INSTALL_PREFIX) path.
ICU_VERSION := 78.3
ICU_URL := https://github.com/unicode-org/icu/releases/download/release-$(ICU_VERSION)/icu4c-$(ICU_VERSION)-sources.tgz
ICU_DIR := icu-$(ICU_VERSION)

$(ICU_DIR).tgz:
	curl -L -o $(ICU_DIR).tgz $(ICU_URL)

$(ICU_DIR)/source/configure: $(ICU_DIR).tgz
	mkdir -p $(ICU_DIR)
	tar xzf $(ICU_DIR).tgz -C $(ICU_DIR) --strip-components=1
	touch $(ICU_DIR)/source/configure

$(INSTALL_PREFIX)/lib/pkgconfig/icu-i18n.pc: $(ICU_DIR)/source/configure
	mkdir -p $(INSTALL_PREFIX)
	cd $(ICU_DIR)/source && ./configure --prefix=$(INSTALL_PREFIX) --disable-static --enable-shared
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && $(MAKE) -C $(ICU_DIR)/source -j
	unset MAKELEVEL && unset MAKEFLAGS && unset MFLAGS && $(MAKE) -C $(ICU_DIR)/source install
ifeq ($(UNAME_S),Darwin)
	# Rewrite absolute install_names to @rpath-relative so downstream binaries
	# embed relocatable LC_LOAD_DYLIB entries.
	@for dylib in $(INSTALL_PREFIX)/lib/libicu*.dylib; do \
		[ -L "$$dylib" ] && continue; \
		install_name_tool -id "@rpath/$$(basename $$dylib)" "$$dylib"; \
		for dep in $$(otool -L "$$dylib" | awk 'NR>1 {print $$1}' | grep libicu); do \
			install_name_tool -change "$$dep" "@rpath/$$(basename $$dep)" "$$dylib"; \
		done; \
	done
endif

.PHONY: icu
icu: $(INSTALL_PREFIX)/lib/pkgconfig/icu-i18n.pc

### other
.PHONY: clean clean-all
clean:
	rm -rf $(INSTALL_PREFIX)
	rm -rf postgresql-*
	rm -rf pgvector-*
	rm -rf icu-*
	rm -rf *.tar.gz *.tgz
