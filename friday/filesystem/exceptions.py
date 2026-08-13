"""
Filesystem errors.

Every failure in the filesystem capability layer is a structured
FilesystemError subclass so callers can distinguish causes without
string parsing.
"""


class FilesystemError(Exception):
    """Base class for all filesystem capability errors."""


class PathDeniedError(FilesystemError):
    """The path is not contained within any authorized root."""


class PermissionDeniedError(FilesystemError):
    """The matched root's grant does not permit the requested operation."""


class RootNotFoundError(FilesystemError):
    """The requested root does not exist or is not a directory."""


class GrantNotFoundError(FilesystemError):
    """No registered grant matches the requested id."""


class PathNotFoundError(FilesystemError):
    """The target path does not exist."""


class IsDirectoryError(FilesystemError):
    """The target path is a directory where a file was expected."""


class NotDirectoryError(FilesystemError):
    """The target path is not a directory where a directory was expected."""


class AlreadyExistsError(FilesystemError):
    """The target already exists and overwrite is not enabled."""


class LimitError(FilesystemError):
    """The operation exceeded a configured size or result limit."""


class RegistryCorruptError(FilesystemError):
    """The project-roots registry file could not be parsed."""
