"""Count task work locally without keeping prompts or replies."""

from contextlib import contextmanager
from contextvars import ContextVar


# Keep simultaneous requests separate, even when they use the same API client.
_current = ContextVar("chexsa_task_metrics", default=None)


@contextmanager
def measure_task(state):
    """Start a fresh set of counters for this request."""
    counters = {
        "model_calls": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "calls_with_usage": 0,
    }
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
    response = create(**arguments)
    if counters is not None:
        _add_usage(counters, getattr(response, "usage", None))
    return response


def _add_usage(counters, usage):
    """Add reported token counts. Missing counts stay unknown, not zero."""
    fields = {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "cached_input_tokens": getattr(
            getattr(usage, "prompt_tokens_details", None), "cached_tokens", None
        ),
    }
    if any(type(value) is int and value >= 0 for value in fields.values()):
        counters["calls_with_usage"] += 1
    for name, value in fields.items():
        if type(value) is int and value >= 0:
            counters[name] = (counters[name] or 0) + value
