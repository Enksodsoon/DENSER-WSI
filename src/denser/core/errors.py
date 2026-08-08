class DenserError(Exception):
    """Base class for expected DENSER failures."""


class IntegrityError(DenserError):
    """Input or persisted state failed integrity verification."""


class GovernanceError(DenserError):
    """Operation violated a governance or public-release boundary."""


class PartitionViolation(DenserError):
    """Operation attempted to cross a frozen experiment partition."""


class FreezeViolation(DenserError):
    """Operation did not match the immutable final freeze."""
