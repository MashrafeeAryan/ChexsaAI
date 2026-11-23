"""Compatibility import for chexsa.desktop.agent."""

import sys
from chexsa.desktop import agent as _impl

sys.modules[__name__] = _impl
