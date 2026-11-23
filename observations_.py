"""Compatibility import for chexsa.core.observations."""

import sys
from chexsa.core.observations import *
from chexsa.core.observations import __dict__ as _module_dict

# Keep legacy imports and patch-based tests pointed at the packaged module.
_current = sys.modules[__name__]
_current.__dict__.update(_module_dict)
