from setuptools import setup

setup(
    setup_requires=["cffi"],
    # dummy but needed for the binaries to work
    cffi_modules=["src/postgresql/_build.py:ffibuilder"], 
)
