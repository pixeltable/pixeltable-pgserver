VERSION=15.5
JOBS_NUMBER=4

## check if this is ubuntu, and libreadline-dev is not installed, then install it/
if [ -f /etc/lsb-release ]; then
    if ! dpkg -s libreadline-dev >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y libreadline-dev
    fi
fi

curl -L -O https://ftp.postgresql.org/pub/source/v${VERSION}/postgresql-${VERSION}.tar.gz
tar -xzf postgresql-${VERSION}.tar.gz
cd postgresql-${VERSION}
./configure --prefix=`pwd`/../src/postgresql
make -j ${JOBS_NUMBER}
make install
cd ..
