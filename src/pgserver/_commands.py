from pathlib import Path
import sys
import subprocess
from typing import Optional, List, Callable
import os
import pwd
import pathlib
import stat
import logging

POSTGRES_BIN_PATH = Path(__file__).parent / "pginstall" / "bin"

def ensure_path_permissions(path: pathlib.Path, username : str):
  """ Ensure target user can traverse path.
      and Ensure target user owns the path.
      Permissions for everyone will be increased to ensure traversal,
      and ownership will be set to the target user if not yet set.

      Path must already exist, as well as the user.
  """

  ## ensure path exists and user exists
  assert path.exists()
  pwentry = pwd.getpwnam(username)

  prefix = path
  while True:
    curr_permissions = prefix.stat().st_mode

    ensure_permissions = curr_permissions | stat.S_IROTH | stat.S_IXOTH

    # TODO: are symlinks handled ok here?
    prefix.chmod(ensure_permissions)

    if prefix == prefix.parent:
      # reached root
      break
    prefix = prefix.parent

  os.chown(str(path), pwentry.pw_uid, pwentry.pw_gid)


def ensure_user_exists(username : str) -> pwd.struct_passwd:
  """ Ensure user `username` exists.
      Returns their pwentry if user exists, otherwise it creates a user through `useradd`.
      Assume permissions to add users.
  """
  try:
    entry = pwd.getpwnam(username)
  except KeyError as e:
    entry = None

  if entry is None:
    subprocess.run(["useradd", "-s", "/bin/bash", username], check=True, capture_output=True, text=True)
    entry = pwd.getpwnam(username)

  return entry

def create_command_function(pg_exe_name : str) -> Callable:
    def command(args : List[str], pgdata : Optional[Path] = None) -> str:
        """
            Run a command with the given command line arguments.
            Args:
                args: The command line arguments to pass to the command as a string,
                a list of options as would be passed to `subprocess.run`
                pgdata: The path to the data directory to use for the command.

            Returns:
                The stdout of the command as a string.
        """
        if pg_exe_name.strip('.exe') in ['initdb', 'pg_ctl', 'pg_dump']:
           assert pgdata is not None, "pgdata must be provided for initdb, pg_ctl, and pg_dump"

        user_name = pwd.getpwuid(os.geteuid()).pw_name
        if os.geteuid() == 0:
            user_name = 'pgserver'

        if pgdata is not None and os.geteuid() == 0:
           ensure_path_permissions(pgdata, user_name)
           ## Postgres complained about the permissions given to the data dir, max is 750
           ## TODO clean up the permissions story.
           pgdata.chmod(0o750)

        if pgdata is not None:
            args = ["-D", str(pgdata)] + args

        full_command_line = [str(POSTGRES_BIN_PATH / pg_exe_name)] + args

        try:
            result = subprocess.run(full_command_line, check=True, capture_output=True, text=True,
                                    user=user_name)

        except subprocess.CalledProcessError as e:
            logging.error(f"Failed command run as user `{user_name}` with error:\n{e=}\nstderr:\n{e.stderr}")
            raise e

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