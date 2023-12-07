from setuptools import setup

with open("README.md") as f:
    long_description = f.read()

setup(
    url="https://github.com/orm011/postgresql-wheel",
    author="Oscar Moll",
    setup_requires=["cffi"],
    cffi_modules=["src/postgresql/build.py:ffibuilder"],
    license="Apache License 2.0",
    keywords=[
        "postgresql",
        "pgvector"
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3 :: Only",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Mathematics",
    ],
)
