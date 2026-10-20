"""
Application-specific exceptions.

Using a typed hierarchy lets the API layer map errors to correct HTTP
status codes, and lets the AI layer distinguish "needs clarification"
from "hard validation failure" from "not allowed."
"""


class InOnError(Exception):
    """Base class for all IN-ON application errors."""


class ValidationError(InOnError):
    """Input failed a business validation rule (e.g. negative amount)."""


class NotFoundError(InOnError):
    """Referenced entity (customer, stock type, etc.) does not exist."""


class InsufficientStockError(InOnError):
    """A sale/stock-out would take a stock type below zero."""


class AmbiguousCommandError(InOnError):
    """Raised by the AI intent layer when a command lacks required info.
    The API layer turns this into a clarification question, never a guess."""


class ConfirmationRequiredError(InOnError):
    """Raised when a destructive or high-risk operation was attempted
    without an explicit confirmation token."""


class ImmutableRecordError(InOnError):
    """Raised when code attempts to directly mutate a balance column
    instead of posting a ledger transaction. This should only ever be
    hit during development/testing - it indicates an architecture violation."""


class UpstreamServiceError(InOnError):
    """Raised when a call to another microservice (chiefly the Ledger
    service) fails, times out, or returns an error we can't otherwise
    classify. Kept distinct from ValidationError/NotFoundError so the
    API layer can return 502/504 instead of implying the caller's own
    request was wrong."""

