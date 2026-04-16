"""Serial device detection for MicroPython devices."""

import re
import subprocess
from typing import List, Optional, Tuple


def list_devices() -> List[Tuple[str, str]]:
    """Return a list of (port, description) tuples for available MicroPython serial devices.

    Parses the output of ``mpremote devs`` and filters for valid serial port
    names on Linux (``/dev/tty*``), macOS (``/dev/tty.*``, ``/dev/cu.*``),
    and Windows (``COM*``).

    Raises ``RuntimeError`` if ``mpremote`` is not installed.
    """
    try:
        result = subprocess.run(
            ["mpremote", "devs"],
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
    except FileNotFoundError:
        raise RuntimeError(
            "mpremote not found. Install it with: pip install mpremote"
        )

    devices: List[Tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # mpremote devs output format:
        #   Linux:   /dev/ttyACM0  2e8a:0005  MicroPython Board in FS mode
        #   macOS:   /dev/cu.usbmodem14201  2e8a:0005  ...
        #   Windows: COM9  2e8a:0005  ...
        match = re.match(r"^(\S+)\s+(.*)", line)
        if match:
            port = match.group(1)
            description = match.group(2).strip()
            # Keep only likely serial/COM ports
            if re.match(
                r"^(COM\d+|/dev/tty[A-Za-z0-9._-]*[A-Za-z0-9]"
                r"|/dev/cu\.[A-Za-z0-9._-]*[A-Za-z0-9])$",
                port,
            ):
                devices.append((port, description))

    return devices


def find_device() -> Optional[str]:
    """Return the first available MicroPython device port, or ``None`` if none found."""
    devices = list_devices()
    if devices:
        return devices[0][0]
    return None
