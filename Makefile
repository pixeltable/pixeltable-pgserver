.DEFAULT_GOAL := build
.PHONY: check-conda build wheel install-wheel install-dev clean test

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
	python -m pip install --force-reinstall dist/*.whl

install-dev: check-conda build
	python -m pip install --force-reinstall -e .[dev,test]

clean:
	rm -rf build/ wheelhouse/ dist/ .eggs/
	$(MAKE) -C pgbuild clean

test:
	python -m pytest -v tests/
