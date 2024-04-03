#! /bin/bash
PROJECT=$1

case "$OSTYPE" in
  linux*)   
    echo "Tests disabled on manylinux conatiner 
        bc postgres prevents running as root"
    ## running on manylinux container as root.
    ## cannot run postgres as root.
    # adduser dbuser
    # mkdir /run/user/`id -u dbuser`
    # chmod -R 777 /run/user/
    # PYTHON=$(which python)
    # BIN=`dirname $PYTHON`
    # ENV=`dirname $BIN`
    # chmod 777 $PROJECT
    # chmod -R 777 $PROJECT/tests
    # chmod -R 777 /tmp # includes ENV
    # su - dbuser -c "$PYTHON -m pytest $PROJECT/tests"
    ;;
  darwin*)  
    echo "Running on Mac" 
    pytest $PROJECT/tests
    ;;
  *)
    echo "Mystery OS:" $OSTYPE; 
    pytest $PROJECT/tests    
    ;;
esac
