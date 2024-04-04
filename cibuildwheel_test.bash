#! /bin/bash
PROJECT=$1

echo "Running on OSTYPE=$OSTYPE with UID=$UID"

case "$OSTYPE" in
    # linux*)
    #     echo "Tests disabled on the manylinux docker container: still debugging test failures only in this environment"
    #     ;;
    *)
        pytest -s -v --log-cli-level=INFO $PROJECT/tests
        ;;
esac
