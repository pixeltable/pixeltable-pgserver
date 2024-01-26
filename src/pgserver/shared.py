from pathlib import Path
import subprocess
from typing import Optional

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

def _process_is_running(pid : int) -> bool:
    assert pid is not None
    try:
        subprocess.run(["kill", "-0", str(pid)], check=True)
        return True
    except subprocess.CalledProcessError:
        pass
    return False
