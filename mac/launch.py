"""What CardCopy.app runs: the same entry point as `python -m cardcopy`."""
import sys

from cardcopy.ui import main

sys.exit(main())
