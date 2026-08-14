"""
Project subsystem errors.

Every failure in the project workspace subsystem is a structured
ProjectError subclass so callers can distinguish causes without string
parsing.
"""


class ProjectError(Exception):
    """Base class for all project subsystem errors."""


class ProjectNotFoundError(ProjectError):
    """No registered project matches the requested id or root."""
