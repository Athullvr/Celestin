class PageIndexError(RuntimeError):
    """A document could not be indexed (bad input, missing dependency)."""


class PageIndexUnavailable(RuntimeError):
    """The PageIndex backend cannot answer right now; callers fall back to other retrieval."""
