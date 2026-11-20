"""Background work that must record every failure instead of stopping its worker."""


class UnexpectedFailure(Exception):
    """A failure outside the expected error types; the original error is its __cause__."""


async def contained(work, expected):
    """Await work, letting expected errors through and wrapping any other failure."""
    try:
        return await work
    except expected:
        raise
    except Exception as error:
        raise UnexpectedFailure from error
