import os

#import versioneer
from setuptools import setup


def package_files(directory):
    paths = []
    for (path, directories, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append(os.path.join("..", "..", path, filename))
    return paths


with open("README.md") as f:
    long_description = f.read()


setup(
    url="https://github.com/michelp/postgresql-wheel",
    author="Michel Pelletier",
    packages=["postgresql"],
    package_dir={"postgresql": "src/postgresql"},
    package_data={"postgresql": package_files("src/postgresql")},
    setup_requires=["cffi"],
    install_requires=["pytest"],
    cffi_modules=["src/postgresql/build.py:ffibuilder"],
    python_requires=">=3.8",
    license="Apache License 2.0",
    keywords=[
        "graphblas",
        "graph",
        "sparse",
        "matrix",
        "suitesparse",
        "hypersparse",
        "hypergraph",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3 :: Only",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Mathematics",
    ],
)
