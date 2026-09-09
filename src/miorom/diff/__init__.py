"""
miorom.diff - Cross-Region Binary Diffing & Symbol Correlator.
"""

from miorom.diff.mapper import BinaryDiffMapper, MatchedBlock
from miorom.diff.porter import CrossRegionPorter, PortReport
from miorom.diff.bindiff import (
    BinDiffEngine,
    BinDiffReport,
    FunctionFingerprint,
    FunctionMatch,
)
from miorom.diff.patch_auditor import PatchAuditor, AuditReport, PatchCollision

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
