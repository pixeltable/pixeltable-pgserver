from pathlib import Path
import sys
import subprocess

pg_bin = Path(__file__).parent / "pginstall" / "bin"

def _prog(name):
    command = str(pg_bin / name)

    def f(cmdline):
        cmdline = f"{command} {cmdline}"
        stdout = subprocess.check_output(cmdline, shell=True)
        return stdout.decode("utf-8")

    return f


this = sys.modules[__name__]

__all__ = []
for path in pg_bin.iterdir():
    p = path.name
    prog = _prog(p)
    setattr(this, p, prog)
    __all__.append(p)