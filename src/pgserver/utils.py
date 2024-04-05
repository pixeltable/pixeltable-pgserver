from pathlib import Path
import typing
from typing import Optional, List
import subprocess
import json
import logging
import hashlib
import socket
import platform
import stat

class PostmasterInfo:
    def __init__(self, pgdata : Path, pid : int, socket_dir : Path):
        self.pgdata = pgdata
        self.pid = pid
        self.socket_dir = socket_dir

    @classmethod
    def read_from_pgdata(cls, pgdata : Path) -> Optional['PostmasterInfo']:
        postmaster_pid = pgdata / 'postmaster.pid'
        if not postmaster_pid.exists():
            return None

        lines = postmaster_pid.read_text().splitlines()
        pid = int(lines[0])
        socket_dir = Path(lines[4])
        socket_path = socket_dir / '.s.PGSQL.5432'
        assert socket_dir.exists()
        assert socket_path.exists()
        assert socket_path.is_socket()

        return cls(postmaster_pid.parent, pid, socket_dir)

if platform.system() != 'Windows' and typing.TYPE_CHECKING:
    import pwd

def process_is_running(pid : int) -> bool:
    assert pid is not None
    try:
        subprocess.run(["kill", "-0", str(pid)], check=True)
        return True
    except subprocess.CalledProcessError:
        pass
    return False

if platform.system() != 'Windows':
    def ensure_user_exists(username : str) -> Optional['pwd.struct_passwd']:
        """ Ensure system user `username` exists.
            Returns their pwentry if user exists, otherwise it creates a user through `useradd`.
            Assume permissions to add users, eg run as root.
        """
        try:
            entry = pwd.getpwnam(username)
        except KeyError:
            entry = None

        if entry is None:
            subprocess.run(["useradd", "-s", "/bin/bash", username], check=True, capture_output=True, text=True)
            entry = pwd.getpwnam(username)

        return entry

    def ensure_prefix_permissions(path: Path):
        """ Ensure target user can traverse prefix to path
            Permissions for everyone will be increased to ensure traversal.
        """
        # ensure path exists and user exists
        assert path.exists()
        prefix = path.parent
        # chmod g+rx,o+rx: enable other users to traverse prefix folders
        g_rx_o_rx = stat.S_IRGRP |  stat.S_IROTH | stat.S_IXGRP | stat.S_IXOTH
        while True:
            curr_permissions = prefix.stat().st_mode
            ensure_permissions = curr_permissions | g_rx_o_rx
            # TODO: are symlinks handled ok here?
            prefix.chmod(ensure_permissions)
            if prefix == prefix.parent: # reached file system root
                break
            prefix = prefix.parent

class DiskList:
    """ A list of integers stored in a file on disk.
    """
    def __init__(self, path : Path):
        self.path = path

    def get_and_add(self, value : int) -> List[int]:
        old_values = self.get()
        values = old_values.copy()
        if value not in values:
            values.append(value)
            self.put(values)
        return old_values

    def get_and_remove(self, value : int) -> List[int]:
        old_values = self.get()
        values = old_values.copy()
        if value in values:
            values.remove(value)
            self.put(values)
        return old_values

    def get(self) -> List[int]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())

    def put(self, values : List[int]) -> None:
        self.path.write_text(json.dumps(values))


def socket_name_length_ok(socket_name : Path):
    ''' checks whether a socket path is too long for domain sockets
        on this system. Returns True if the socket path is ok, False if it is too long.
    '''
    if socket_name.exists():
        return socket_name.is_socket()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(socket_name))
        return True
    except OSError as err:
        if 'AF_UNIX path too long' in str(err):
            return False
        raise err
    finally:
        sock.close()
        socket_name.unlink(missing_ok=True)

def find_suitable_socket_dir(pgdata, runtime_path) -> Path:
    """ Assumes server is not running. Returns a suitable directory for used as pg_ctl -o '-k ' option.
        Usually, this is the same directory as the pgdata directory.
        However, if the pgdata directory exceeds the maximum length for domain sockets on this system,
        a different directory will be used.
    """
    # find a suitable directory for the domain socket
    # 1. pgdata. simplest approach, but can be too long for unix socket depending on the path
    # 2. runtime_path. This is a directory that is intended for storing runtime data.

    # for shared folders, use a hash of the path to avoid collisions of different folders
    # use a hash of the pgdata path combined with inode number to avoid collisions
    string_identifier = f'{pgdata}-{pgdata.stat().st_ino}'
    path_hash = hashlib.sha256(string_identifier.encode()).hexdigest()[:10]

    candidate_socket_dir = [
        pgdata,
        runtime_path / path_hash,
    ]

    ok_path = None
    for path in candidate_socket_dir:
        path.mkdir(parents=True, exist_ok=True)
        # name used by postgresql for domain socket is .s.PGSQL.5432
        if socket_name_length_ok(path / '.s.PGSQL.5432'):
            ok_path = path
            logging.info(f"Using socket path: {path}")
            break
        else:
            logging.info(f"Socket path too long: {path}. Will try a different directory for socket.")

    if ok_path is None:
        raise RuntimeError("Could not find a suitable socket path")

    return ok_path

def find_suitable_port(address : Optional[str] = None) -> int:
    """Find an available TCP port."""
    if address is None:
        address = '127.0.0.1'
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((address, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


__all__ = ['get_server']







