import sys

from fretwise.cli import main

# If invoked with no subcommand, default to `gui` (launch server + open browser).
if len(sys.argv) == 1:
    sys.argv.append("gui")

main()
