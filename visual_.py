"""Compatibility import for chexsa.desktop.visual."""

import sys
from chexsa.desktop import visual as _impl

sys.modules[__name__] = _impl
