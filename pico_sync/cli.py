"""Click CLI for pico-sync.

This module defines all ``pico-sync`` sub-commands.  Every command
auto-detects the serial port unless ``--port`` / ``-p`` is specified.
"""

import os
import sys
from typing import Optional

# Support running this file directly: ``python pico_sync/cli.py``
if __name__ == "__main__" and __package__ is None:
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    __package__ = "pico_sync"

import click

from .device import find_device, list_devices
from . import commands


def _resolve_port(port: Optional[str]) -> str:
    """Return *port* if given, otherwise auto-detect one or exit."""
    if port:
        return port
    detected = find_device()
    if detected is None:
        click.echo(
            "Error: No MicroPython device found. Connect a Pico or specify --port.",
            err=True,
        )
        sys.exit(1)
    click.echo(f"Auto-detected device: {detected}", err=True)
    return detected


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="pico-sync")
def main():
    """pico-sync – manage files on a Raspberry Pi Pico running MicroPython."""


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------

@main.command("devices")
def cmd_devices():
    """List available MicroPython serial devices."""
    rc = commands.cmd_devs()
    sys.exit(rc)


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command("ls")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port (e.g. COM9 or /dev/ttyUSB0). Auto-detected if omitted.")
@click.argument("path", default="/")
def cmd_ls(port: Optional[str], path: str):
    """List files on the Pico.

    PATH defaults to / (the root of the filesystem).
    """
    port = _resolve_port(port)
    rc = commands.cmd_ls(port, path)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------

@main.command("mkdir")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.argument("path")
def cmd_mkdir(port: Optional[str], path: str):
    """Create a directory on the Pico."""
    port = _resolve_port(port)
    rc = commands.cmd_mkdir(port, path)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

@main.command("rm")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.option("--recursive", "-r", is_flag=True, default=False,
              help="Remove directory and its contents recursively.")
@click.argument("path")
def cmd_rm(port: Optional[str], recursive: bool, path: str):
    """Remove a file or folder on the Pico."""
    port = _resolve_port(port)
    rc = commands.cmd_rm(port, path, recursive=recursive)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# copy  (PC → Pico)
# ---------------------------------------------------------------------------

@main.command("copy")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.option("--force", is_flag=True, default=False,
              help="Force overwrite of existing files.")
@click.option("--no-skip", "no_skip", is_flag=True, default=False,
              help="Do not skip unchanged files (copy everything).")
@click.argument("src")
@click.argument("dest")
def cmd_copy(port: Optional[str], force: bool, no_skip: bool, src: str, dest: str):
    """Copy a file or folder to the Pico.

    SRC is a local path; DEST is the remote path (e.g. :main.py or :/lib/).
    If SRC is a directory the copy is recursive.
    """
    port = _resolve_port(port)
    skip_unchanged = not no_skip
    if os.path.isdir(src):
        rc = commands.cmd_cp_dir(port, src, dest, force=force, skip_unchanged=skip_unchanged)
    else:
        rc = commands.cmd_cp_file(port, src, dest, force=force, skip_unchanged=skip_unchanged)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# pull  (Pico → PC)
# ---------------------------------------------------------------------------

@main.command("pull")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.argument("remote_path")
@click.argument("local_dest")
def cmd_pull(port: Optional[str], remote_path: str, local_dest: str):
    """Copy a file or folder FROM the Pico to the local machine.

    REMOTE_PATH is the path on the Pico (e.g. /main.py or /lib).
    LOCAL_DEST is the local destination path.

    Examples:

    \b
        pico-sync pull /main.py ./main.py
        pico-sync pull /lib ./backup/lib
    """
    port = _resolve_port(port)
    # Determine whether the remote path is a directory by listing it
    entries = commands.ls_remote(port, remote_path)
    if entries is not None:
        rc = commands.cmd_cp_dir_from_pico(port, remote_path, local_dest)
    else:
        rc = commands.cmd_cp_file_from_pico(port, remote_path, local_dest)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

@main.command("reset")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
def cmd_reset(port: Optional[str]):
    """Soft-reset the Pico."""
    port = _resolve_port(port)
    rc = commands.cmd_reset(port)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# mount
# ---------------------------------------------------------------------------

@main.command("mount")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.argument("local_dir")
def cmd_mount(port: Optional[str], local_dir: str):
    """Mount a local directory on the Pico for live development."""
    port = _resolve_port(port)
    rc = commands.cmd_mount(port, local_dir)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------

@main.command("deploy")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.option("--force", is_flag=True, default=False,
              help="Force overwrite of existing files.")
@click.option("--reset", "do_reset", is_flag=True, default=False,
              help="Soft-reset the Pico after deployment.")
@click.option("--no-skip", "no_skip", is_flag=True, default=False,
              help="Do not skip unchanged files.")
@click.argument("src")
@click.argument("dest", default=":")
def cmd_deploy(
    port: Optional[str],
    force: bool,
    do_reset: bool,
    no_skip: bool,
    src: str,
    dest: str,
):
    """Deploy a file or folder to the Pico.

    SRC is the local file or directory.  DEST is the Pico destination
    (default ``:`` = root).  Use --reset to soft-reset after deployment.
    """
    port = _resolve_port(port)
    skip_unchanged = not no_skip
    rc = commands.cmd_deploy(
        port, src, dest,
        force=force, reset=do_reset, skip_unchanged=skip_unchanged,
    )
    sys.exit(rc)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@main.command("run")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.argument("file")
def cmd_run(port: Optional[str], file: str):
    """Run a Python file on the Pico, streaming output live.

    FILE is the local Python script to execute on the Pico.
    """
    port = _resolve_port(port)
    rc = commands.cmd_run(port, file)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------

@main.command("exec")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.argument("code")
def cmd_exec(port: Optional[str], code: str):
    """Execute a Python code snippet on the Pico.

    CODE is a Python expression or statement string.
    """
    port = _resolve_port(port)
    rc = commands.cmd_exec(port, code)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# repl
# ---------------------------------------------------------------------------

@main.command("repl")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
def cmd_repl(port: Optional[str]):
    """Open an interactive MicroPython REPL session on the Pico."""
    port = _resolve_port(port)
    rc = commands.cmd_repl(port)
    sys.exit(rc)


# ---------------------------------------------------------------------------
# hash
# ---------------------------------------------------------------------------

@main.command("hash")
@click.option("--port", "-p", default=None, metavar="PORT",
              help="Serial port. Auto-detected if omitted.")
@click.option("--algorithm", "-a", default="md5", show_default=True, metavar="ALGO",
              help="Hash algorithm: md5 or sha256.")
@click.argument("local_path")
@click.argument("remote_path", required=False, default=None)
def cmd_hash_file(
    port: Optional[str],
    algorithm: str,
    local_path: str,
    remote_path: Optional[str],
):
    """Show the hash of a local file and optionally compare with a Pico file.

    LOCAL_PATH is the local file to hash.

    REMOTE_PATH (optional) is the Pico path (e.g. /main.py).  When given,
    both hashes are printed and a MATCH / DIFFER verdict is shown.
    """
    if remote_path is not None:
        port = _resolve_port(port)
    rc = commands.cmd_hash(port, local_path, remote_path, algorithm=algorithm)
    sys.exit(rc)


if __name__ == "__main__":
    main()
