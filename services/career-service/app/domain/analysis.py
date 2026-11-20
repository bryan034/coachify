"""Errors for stored analysis records that conflict with their inputs."""


class ContractConflict(ValueError):
    """Recoverable missing, foreign or stale input; never publish this result."""
