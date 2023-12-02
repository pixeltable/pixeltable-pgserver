VERSION=15.5
JOBS_NUMBER=4

curl -L -O https://ftp.postgresql.org/pub/source/v${VERSION}/postgresql-${VERSION}.tar.gz
tar -xzf postgresql-${VERSION}.tar.gz
cd postgresql-${VERSION}
./configure --prefix=`pwd`/../src/postgresql
make -j ${JOBS_NUMBER} world-bin
make install-world-bin
cd ..
