"""Allow running pico-sync as a module: python -m pico_sync.

Launches the GUI by default.  Pass ``--cli`` (or run ``pico-sync`` directly)
for the command-line interface.
"""

import sys


def _main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.argv.pop(1)  # strip the --cli flag before Click sees it
        from pico_sync.cli import main
        main()
    else:
        from pico_sync.gui import launch
        launch()


if __name__ == "__main__":
    _main()
