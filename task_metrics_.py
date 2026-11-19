"""Count task work locally without keeping prompts or replies."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter


# Keep simultaneous requests separate, even when they use the same API client.
_current = ContextVar("chexsa_task_metrics", default=None)


@contextmanager
def measure_task(state):
    """Start a fresh set of counters for this request."""
    counters = {
        "model_calls": 0,
        "failed_model_calls": 0,
        "outcome": "unverified",
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "calls_with_usage": 0,
        "seconds": {},
    }
    state["last_metrics"] = counters
    token = _current.set(counters)
    started = perf_counter()
    try:
        yield counters
    except KeyboardInterrupt:
        counters["outcome"] = "cancelled"
        raise
    except Exception:
        counters["outcome"] = "failed"
        raise
    finally:
        counters["seconds"]["task"] = perf_counter() - started
        _current.reset(token)


def time_step(phase):
    """Measure a step in a task, leaving calls outside tasks untouched."""
    def wrap(function):
        @wraps(function)
        def timed(*args, **kwargs):
            counters = _current.get()
            if counters is None:
                return function(*args, **kwargs)
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                seconds = counters["seconds"]
                seconds[phase] = seconds.get(phase, 0) + perf_counter() - started
        return timed
    return wrap


@time_step("model")
def call_model(create, **arguments):
    """Count an attempted model call, including a request that raises an error."""
    counters = _current.get()
    if counters is not None:
        counters["model_calls"] += 1
    try:
        response = create(**arguments)
    except Exception:
        if counters is not None:
            counters["failed_model_calls"] += 1
        raise
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
