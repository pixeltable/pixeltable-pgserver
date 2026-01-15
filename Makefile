.DEFAULT_GOAL := build
.PHONY: check-conda build wheel install-wheel install-dev test clean

check-conda:
ifdef CONDA_DEFAULT_ENV
ifeq ($(CONDA_DEFAULT_ENV),base)
	$(error pixeltable-pgserver must be installed from a conda environment (not `base`))
endif
else
	$(error pixeltable-pgserver must be installed from a conda environment)
endif

build:
	$(MAKE) -d -C pgbuild all

wheel: build
	python setup.py bdist_wheel

install-wheel: wheel
	python -m pip install dist/*.whl

install-dev: check-conda build
	python -m pip install -e .[dev,test]

test: pytest check

pytest:
	python -m pytest -v tests/

check:
	mypy src tests
	ruff check src tests
	ruff format --check src tests
	ruff check --select I src tests

format:
	ruff format src tests
	ruff check --select I --fix src tests

clean:
	rm -rf build/ wheelhouse/ dist/ .eggs/
	$(MAKE) -C pgbuild clean
