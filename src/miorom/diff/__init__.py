"""
miorom.diff - Cross-Region Binary Diffing & Symbol Correlator.
"""

from miorom.diff.bindiff import (
    BinDiffEngine,
    BinDiffReport,
    FunctionFingerprint,
    FunctionMatch,
)
from miorom.diff.mapper import BinaryDiffMapper, MatchedBlock
from miorom.diff.patch_auditor import AuditReport, PatchAuditor, PatchCollision
from miorom.diff.porter import CrossRegionPorter, PortReport

__all__ = [
    "BinaryDiffMapper",
    "MatchedBlock",
    "CrossRegionPorter",
    "PortReport",
    "BinDiffEngine",
    "BinDiffReport",
    "FunctionFingerprint",
    "FunctionMatch",
    "PatchAuditor",
    "AuditReport",
    "PatchCollision",
]
