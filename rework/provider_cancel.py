"""Cancellation context for the existing provider transport, including nested calls."""
from contextvars import ContextVar
from contextlib import contextmanager

current = ContextVar('logis_provider_cancel', default=lambda: False)


class ProviderCanceled(Exception):
    pass


@contextmanager
def cancellation(check):
    token = current.set(check)
    try:
        yield
    finally:
        current.reset(token)
