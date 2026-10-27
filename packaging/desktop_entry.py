"""Point d’entrée du binaire desktop construit avec PyInstaller."""

import sys

from kubemap.__main__ import main

main(["--desktop", *sys.argv[1:]])
