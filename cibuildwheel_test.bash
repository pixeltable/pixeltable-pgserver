#! /bin/bash
PROJECT=$1

echo "Running tests on OSTYPE=$OSTYPE with UID=$UID"
pytest -v $PROJECT/tests