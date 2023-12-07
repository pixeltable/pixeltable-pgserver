## check if this is ubuntu, and libreadline-dev is not installed, then install it/
if [ -f /etc/lsb-release ]; then
    if ! dpkg -s libreadline-dev >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y libreadline-dev
    fi
fi
