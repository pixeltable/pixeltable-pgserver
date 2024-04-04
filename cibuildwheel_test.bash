#! /bin/bash
PROJECT=$1

echo "Running on OSTYPE=$OSTYPE with UID=$UID"

case "$OSTYPE" in
    linux*)
        echo "Tests disabled on the manylinux container bc still debugging running in those environment constraints"
        ;;
    *)
        pytest -v $PROJECT/tests
        ;;
esac
