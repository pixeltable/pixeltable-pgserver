import logging
import platform
import subprocess
import tempfile
from typing import Any, Sequence

from .utils import POSTGRES_BIN_PATH

_logger = logging.getLogger('pixeltable_pgserver')


def pgexec(command: str, args: Sequence[str], **subprocess_kwargs: Any) -> str:
    """
    Run a postgres command with the given command line arguments.
    Args:
        args: The command line arguments to pass to the command as a string,
            a list of options as would be passed to `subprocess.run`
        pgdata: The path to the data directory to use for the command.
            If the command does not need a data directory, this should be None.
        kwargs: Additional keyword arguments to pass to `subprocess.run`, eg user, timeout.

    Returns:
        The stdout of the command as a string.
    """

    if platform.system() == 'Windows':
        command += '.exe'

    cmdline = (str(POSTGRES_BIN_PATH / command), *args)

    with (
        tempfile.TemporaryFile('w+', encoding='utf-8') as stdout,
        tempfile.TemporaryFile('w+', encoding='utf-8') as stderr,
    ):
        try:
            _logger.info(f'Running commandline:\n{cmdline}\nwith subprocess kwargs: {subprocess_kwargs}')
            # capture_output=True, as well as using stdout=subprocess.PIPE and stderr=subprocess.PIPE
            # can cause this call to hang, even with a time-out depending on the command, (pg_ctl)
            # so we use two temporary files instead
            result = subprocess.run(cmdline, check=True, stdout=stdout, stderr=stderr, text=True, **subprocess_kwargs)
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read()
            error = stderr.read()
            _logger.info(
                'Successful postgres command %s with kwargs: `%s`\nstdout:\n%s\n---\nstderr:\n%s\n---\n',
                result.args,
                subprocess_kwargs,
                output,
                error,
            )
        except subprocess.CalledProcessError as err:
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read()
            error = stderr.read()
            _logger.error(
                'Failed postgres command %s with kwargs: `%s`:\nerror:\n%s\nstdout:\n%s\n---\nstderr:\n%s\n---\n',
                err.args,
                subprocess_kwargs,
                str(err),
                output,
                error,
            )
            raise err

    return output
