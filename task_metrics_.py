"""Count task work locally without keeping prompts or replies."""

from contextlib import contextmanager
from contextvars import ContextVar


# Keep simultaneous requests separate, even when they use the same API client.
_current = ContextVar("chexsa_task_metrics", default=None)


@contextmanager
def measure_task(state):
    """Start a fresh set of counters for this request."""
    counters = {"model_calls": 0}
    state["last_metrics"] = counters
    token = _current.set(counters)
    try:
        yield counters
    finally:
        _current.reset(token)


def call_model(create, **arguments):
    """Count an attempted model call, including a request that raises an error."""
    counters = _current.get()
    if counters is not None:
        counters["model_calls"] += 1
    return create(**arguments)
