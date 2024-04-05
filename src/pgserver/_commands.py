from pathlib import Path
import sys
import subprocess
from typing import Optional, List, Callable
import logging

POSTGRES_BIN_PATH = Path(__file__).parent / "pginstall" / "bin"

def create_command_function(pg_exe_name : str) -> Callable:
    def command(args : List[str], pgdata : Optional[Path] = None, user : Optional[str] = None) -> str:
        """
            Run a command with the given command line arguments.
            Args:
                args: The command line arguments to pass to the command as a string,
                a list of options as would be passed to `subprocess.run`
                pgdata: The path to the data directory to use for the command.
                    If the command does not need a data directory, this should be None.
                user: The user to run the command as. If None, the current user is used.

            Returns:
                The stdout of the command as a string.
        """
        if pg_exe_name.strip('.exe') in ['initdb', 'pg_ctl', 'pg_dump']:
           assert pgdata is not None, "pgdata must be provided for initdb, pg_ctl, and pg_dump"

        if pgdata is not None:
            args = ["-D", str(pgdata)] + args

        full_command_line = [str(POSTGRES_BIN_PATH / pg_exe_name)] + args

        try:
            result = subprocess.run(full_command_line, check=True, capture_output=True, text=True,
                                    user=user)
            logging.info("Successful postgres command %s as user `%s`\nstdout:\n%s\n---\nstderr:\n%s\n---\n",
                         result.args, user, result.stdout, result.stderr)
        except subprocess.CalledProcessError as err:
            logging.error("Failed postgres command %s as user `%s`:\nerror:\n%s\nstdout:\n%s\n---\nstderr:\n%s\n---\n",
                          err.args, user, str(err), err.stdout, err.stderr)
            raise err

        return result.stdout

    return command

__all__ = []
def _init():
    for path in POSTGRES_BIN_PATH.iterdir():
        exe_name = path.name
        prog = create_command_function(exe_name)
        # Strip .exe suffix for Windows compatibility
        function_name = exe_name.strip('.exe')
        setattr(sys.modules[__name__], function_name, prog)
        __all__.append(function_name)

_init()