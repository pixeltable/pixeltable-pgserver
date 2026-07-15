#! /bin/bash
PROJECT=$1

echo "Running on OSTYPE=$OSTYPE with UID=$UID"

case "$OSTYPE" in
    # linux *)
    #     echo "Tests disabled on the manylinux docker container for now"
    #     ;;
    *)
        pytest -v "$PROJECT/tests"
        ;;
esac
