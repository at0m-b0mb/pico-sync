"""mpremote command wrappers for pico-sync operations.

Every public function in this module maps to a single logical operation
(ls, cp, rm, reset, …) and returns an ``int`` exit code (0 = success).
The module is used by both the CLI (``cli.py``) and the GUI (``gui.py``).
"""

import hashlib
import os
import subprocess
import sys
from typing import List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(args: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run a subprocess command, streaming output unless *capture* is True."""
    try:
        if capture:
            result = subprocess.run(args, capture_output=True, text=True)
        else:
            result = subprocess.run(args, text=True)
    except FileNotFoundError:
        cmd = args[0] if args else "command"
        msg = f"Error: '{cmd}' not found."
        if cmd == "mpremote":
            msg += " Install it with: pip install mpremote"
        print(msg, file=sys.stderr)
        sys.exit(1)
    return result


def _mpremote_base(port: str) -> List[str]:
    """Return the common prefix for every mpremote invocation."""
    return ["mpremote", "connect", port]


def _coerce_remote_path(path: str) -> str:
    """Ensure a remote path is prefixed with ``:``.

    mpremote uses a leading colon to distinguish remote paths from local
    ones (e.g. ``:/lib/`` vs ``./lib/``).
    """
    if not path.startswith(":"):
        return ":" + path
    return path


# ---------------------------------------------------------------------------
# Device listing
# ---------------------------------------------------------------------------

def cmd_devs() -> int:
    """Run ``mpremote devs`` and stream output.  Returns the exit code."""
    result = _run(["mpremote", "devs"])
    return result.returncode


# ---------------------------------------------------------------------------
# ls  (with capture variant for GUI / programmatic use)
# ---------------------------------------------------------------------------

def cmd_ls(port: str, path: str = "/") -> int:
    """List files on the Pico at the given *path*.  Streams to stdout."""
    remote = _coerce_remote_path(path)
    args = _mpremote_base(port) + ["ls", remote]
    result = _run(args)
    return result.returncode


def ls_remote(port: str, path: str = "/") -> Optional[List[dict]]:
    """Return structured entries under remote *path*, or ``None`` on error.

    Each entry is a dict ``{'name': str, 'is_dir': bool}``.  This helper
    is used by the GUI for Pico-to-local recursive copy and for the
    ``pull`` CLI command to decide whether a remote path is a directory.
    """
    remote = _coerce_remote_path(path)
    args = _mpremote_base(port) + ["ls", remote]
    result = _run(args, capture=True)
    if result.returncode != 0:
        return None
    entries: List[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # mpremote ls output: "         0 filename" or "      <dir> dirname/"
        # Only accept lines whose first token is a file size (digits), filtering
        # out any header lines like "ls /:" that some mpremote versions emit.
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            name = parts[1]
            is_dir = name.endswith("/")
            entries.append({"name": name.rstrip("/"), "is_dir": is_dir})
    return entries


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------

def cmd_mkdir(port: str, path: str) -> int:
    """Create a directory on the Pico."""
    remote = _coerce_remote_path(path)
    args = _mpremote_base(port) + ["mkdir", remote]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# rm  (with recursive support)
# ---------------------------------------------------------------------------

def _ls_remote_names(port: str, path: str) -> Optional[List[str]]:
    """Return entry names under *path*, or ``None`` if it is not a directory."""
    remote = _coerce_remote_path(path)
    args = _mpremote_base(port) + ["ls", remote]
    result = _run(args, capture=True)
    if result.returncode != 0:
        return None
    entries: List[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        # Only accept lines where the first token is a file size (digits only).
        # This filters out any header lines (e.g. "ls /:") that some mpremote
        # versions may emit.
        if len(parts) == 2 and parts[0].isdigit():
            entries.append(parts[1].rstrip("/"))
    return entries


def _rmdir_remote(port: str, path: str) -> int:
    """Remove an empty remote directory, falling back to exec on older mpremote."""
    remote = _coerce_remote_path(path)
    args = _mpremote_base(port) + ["rmdir", remote]
    result = _run(args, capture=True)
    if result.returncode == 0:
        return 0
    # Fallback: use MicroPython exec in case 'rmdir' subcommand is unsupported
    code = f"import os; os.rmdir({path!r})"
    fallback = _mpremote_base(port) + ["exec", code]
    result = _run(fallback, capture=True)
    return result.returncode


def _rm_recursive(port: str, path: str) -> int:
    """Recursively remove a remote *path* (file or directory)."""
    path = path.rstrip("/")
    remote = _coerce_remote_path(path)

    entries = _ls_remote_names(port, path)
    if entries is not None:
        # It's a directory — recurse into children first
        for entry in entries:
            child = path.rstrip("/") + "/" + entry
            rc = _rm_recursive(port, child)
            if rc != 0:
                return rc
        # Now remove the (now-empty) directory itself
        return _rmdir_remote(port, path)
    else:
        # It's a file (or a path that can't be listed) — remove directly
        args = _mpremote_base(port) + ["rm", remote]
        result = _run(args, capture=True)
        return result.returncode


def cmd_rm(port: str, path: str, recursive: bool = False) -> int:
    """Remove a file or folder on the Pico.

    When *recursive* is ``True`` a non-empty directory and all of its
    contents are removed.  Without the flag, non-empty directories cause
    an error message and return code 1.
    """
    if recursive:
        return _rm_recursive(port, path)

    remote = _coerce_remote_path(path)

    # Determine whether *path* is a directory
    entries = _ls_remote_names(port, path)
    if entries is not None:
        # It's a directory
        if entries:
            print(
                f"Error: directory '{path}' is not empty. Use --recursive.",
                file=sys.stderr,
            )
            return 1
        args = _mpremote_base(port) + ["rmdir", remote]
    else:
        args = _mpremote_base(port) + ["rm", remote]

    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# copy: PC → Pico
# ---------------------------------------------------------------------------

def cmd_cp_file(
    port: str,
    src: str,
    dest: str,
    force: bool = False,
    skip_unchanged: bool = True,
) -> int:
    """Copy a single local file to the Pico.

    *skip_unchanged* uses ``--check`` to avoid re-uploading identical
    files.  If the installed mpremote does not support ``--check`` the
    flag is silently dropped.
    """
    remote_dest = _coerce_remote_path(dest)
    if force:
        _run(_mpremote_base(port) + ["rm", remote_dest], capture=True)

    args = _mpremote_base(port) + ["cp"]
    use_check = skip_unchanged and not force

    if use_check:
        args_check = args + ["--check", src, remote_dest]
        result = _run(args_check, capture=True)
        if result.returncode != 0 and "unrecognized" in (result.stderr or "").lower():
            # --check not supported — fall back without it
            result = _run(args + [src, remote_dest])
            return result.returncode
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    args += [src, remote_dest]
    result = _run(args)
    return result.returncode


def cmd_cp_dir(
    port: str,
    src: str,
    dest: str,
    force: bool = False,
    skip_unchanged: bool = True,
) -> int:
    """Recursively copy a local directory to the Pico."""
    src_path = src.rstrip("/") + "/"
    remote_dest = _coerce_remote_path(dest.rstrip("/") + "/")

    if force:
        _rm_recursive(port, dest.rstrip("/"))

    args = _mpremote_base(port) + ["cp", "-r"]
    use_check = skip_unchanged and not force

    if use_check:
        args_check = args + ["--check", src_path, remote_dest]
        result = _run(args_check, capture=True)
        if result.returncode != 0 and "unrecognized" in (result.stderr or "").lower():
            result = _run(args + [src_path, remote_dest])
            return result.returncode
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    args += [src_path, remote_dest]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# copy: Pico → PC
# ---------------------------------------------------------------------------

def cmd_cp_file_from_pico(port: str, remote_path: str, local_dest: str) -> int:
    """Copy a single file from the Pico to the local filesystem."""
    remote = _coerce_remote_path(remote_path)
    args = _mpremote_base(port) + ["cp", remote, local_dest]
    result = _run(args)
    return result.returncode


def cmd_cp_dir_from_pico(port: str, remote_path: str, local_dest: str) -> int:
    """Recursively copy a directory from the Pico to the local filesystem.

    Tries the native ``mpremote cp -r :src/ dest/`` first.  If that fails
    (older mpremote builds) it falls back to walking the remote tree
    manually, recreating directories locally, and copying each file.
    """
    remote_path = remote_path.rstrip("/")
    local_dest = local_dest.rstrip("/") + "/"
    remote = _coerce_remote_path(remote_path + "/")

    # Try native recursive copy first
    args = _mpremote_base(port) + ["cp", "-r", remote, local_dest]
    result = _run(args, capture=True)
    if result.returncode == 0:
        if result.stdout:
            print(result.stdout, end="")
        return 0

    # Fallback: manual recursive walk
    return _pull_recursive(port, remote_path, local_dest.rstrip("/"))


def _pull_recursive(port: str, remote_dir: str, local_dir: str) -> int:
    """Walk a remote directory and copy every file into *local_dir*."""
    os.makedirs(local_dir, exist_ok=True)
    entries = ls_remote(port, remote_dir)
    if entries is None:
        # It's actually a single file, not a directory
        fname = os.path.basename(remote_dir)
        local_file = os.path.join(local_dir, fname)
        return cmd_cp_file_from_pico(port, remote_dir, local_file)

    for entry in entries:
        child_remote = remote_dir.rstrip("/") + "/" + entry["name"]
        child_local = os.path.join(local_dir, entry["name"])
        if entry["is_dir"]:
            rc = _pull_recursive(port, child_remote, child_local)
        else:
            rc = cmd_cp_file_from_pico(port, child_remote, child_local)
        if rc != 0:
            return rc
    return 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def cmd_reset(port: str) -> int:
    """Soft-reset the Pico."""
    args = _mpremote_base(port) + ["reset"]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# mount
# ---------------------------------------------------------------------------

def cmd_mount(port: str, local_dir: str) -> int:
    """Mount a local directory on the Pico for live development."""
    args = _mpremote_base(port) + ["mount", local_dir]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# deploy  (composite: copy + optional reset)
# ---------------------------------------------------------------------------

def cmd_deploy(
    port: str,
    src: str,
    dest: str = ":",
    force: bool = False,
    reset: bool = False,
    skip_unchanged: bool = True,
) -> int:
    """Deploy a file or folder to the Pico, optionally resetting afterwards."""
    if os.path.isdir(src):
        rc = cmd_cp_dir(port, src, dest, force=force, skip_unchanged=skip_unchanged)
    else:
        rc = cmd_cp_file(port, src, dest, force=force, skip_unchanged=skip_unchanged)

    if rc != 0:
        return rc

    if reset:
        rc = cmd_reset(port)

    return rc


# ---------------------------------------------------------------------------
# run  (execute a file on the Pico)
# ---------------------------------------------------------------------------

def cmd_run(port: str, file: str) -> int:
    """Run a local Python file on the Pico, streaming output live."""
    args = _mpremote_base(port) + ["run", file]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# exec  (execute a code snippet on the Pico)
# ---------------------------------------------------------------------------

def cmd_exec(port: str, code: str) -> int:
    """Execute a Python code string on the Pico."""
    args = _mpremote_base(port) + ["exec", code]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# repl  (interactive REPL)
# ---------------------------------------------------------------------------

def cmd_repl(port: str) -> int:
    """Open an interactive MicroPython REPL on the Pico."""
    args = _mpremote_base(port) + ["repl"]
    result = _run(args)
    return result.returncode


# ---------------------------------------------------------------------------
# file hash
# ---------------------------------------------------------------------------

_PICO_HASH_CODE = """\
import hashlib, binascii
h = hashlib.{algo}()
f = open({path!r}, 'rb')
while True:
    d = f.read(512)
    if not d:
        break
    h.update(d)
f.close()
print(binascii.hexlify(h.digest()).decode())
"""


def local_file_hash(path: str, algorithm: str = "md5") -> Optional[str]:
    """Return the hex digest of a local file, or ``None`` on error."""
    try:
        h = hashlib.new(algorithm)
    except ValueError:
        return None
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def remote_file_hash(
    port: str, remote_path: str, algorithm: str = "md5"
) -> Optional[str]:
    """Return the hex digest of a file on the Pico, or ``None`` on error.

    Executes a small MicroPython snippet on the device to compute the hash.
    """
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path
    code = _PICO_HASH_CODE.format(algo=algorithm, path=remote_path)
    result = _run(["mpremote", "connect", port, "exec", code], capture=True)
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def cmd_hash(
    port: str,
    local_path: str,
    remote_path: Optional[str] = None,
    algorithm: str = "md5",
) -> int:
    """Print the hash of a local file and optionally compare with a Pico file."""
    local_hash = local_file_hash(local_path, algorithm)
    if local_hash is None:
        print(f"Error: could not hash local file: {local_path}", file=sys.stderr)
        return 1
    print(f"Local  {algorithm}: {local_hash}  {local_path}")

    if remote_path is None:
        return 0

    remote_hash = remote_file_hash(port, remote_path, algorithm)
    if remote_hash is None:
        print(f"Error: could not hash remote file: {remote_path}", file=sys.stderr)
        return 1

    match_str = "MATCH" if local_hash == remote_hash else "DIFFER"
    print(f"Remote {algorithm}: {remote_hash}  {remote_path}")
    print(f"Result: {match_str}")
    return 0
