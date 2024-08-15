from setuptools import setup

setup(
    setup_requires=["cffi"],
    # dummy but needed for the binaries to work
    cffi_modules=["src/pixeltable_pgserver/_build.py:ffibuilder"],
)
