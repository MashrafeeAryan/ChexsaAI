"""Compatibility import for chexsa.core.observations."""

import sys
from chexsa.core import observations as _impl

sys.modules[__name__] = _impl
