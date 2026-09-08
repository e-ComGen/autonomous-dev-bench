"""Shared source-integrity errors; re-exported by checkout for compatibility."""


class CheckoutError(RuntimeError):
    pass


class SourceTreeDigestMismatch(CheckoutError):
    pass
