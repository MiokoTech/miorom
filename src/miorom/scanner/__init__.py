"""
miorom.scanner - Binary Analysis, Deep Inspection, and Container Fingerprinting.
Includes signature scanning, Shannon entropy distribution, string scanning, and pointer discovery.
"""

from miorom.core.scanner import (
    CandidatePointerTable,
    FoundString,
    PointerScanner,
    StringScanner,
    TextBlock,
)
from miorom.scanner.deep import (
    BinaryFingerprint,
    DeepScanReport,
    DeepScanner,
    calculate_block_entropy,
    calculate_entropy,
)
from miorom.scanner.inspector import (
    EncodingCandidate,
    InspectionReport,
    SmartInspector,
)
from miorom.scanner.crypto import CryptoMatch, CryptoReport, CryptoScanner
from miorom.scanner.xref import XRefType, XRefEntry, XRefGraph, XRefAnalyzer
from miorom.scanner.pattern import AOBPatternScanner, PatternMatch, CompiledPattern
from miorom.scanner.triage import RomTriageEngine, TriageReport, FileTriageRecord, AssetType
from miorom.scanner.table_detector import HeuristicTableDetector, TableCandidate

__all__ = [
    "BinaryFingerprint",
    "CandidatePointerTable",
    "DeepScanReport",
    "DeepScanner",
    "EncodingCandidate",
    "FoundString",
    "InspectionReport",
    "PointerScanner",
    "SmartInspector",
    "StringScanner",
    "TextBlock",
    "calculate_block_entropy",
    "calculate_entropy",
    "CryptoMatch",
    "CryptoReport",
    "CryptoScanner",
    "XRefType",
    "XRefEntry",
    "XRefGraph",
    "XRefAnalyzer",
    "AOBPatternScanner",
    "PatternMatch",
    "CompiledPattern",
    "RomTriageEngine",
    "TriageReport",
    "FileTriageRecord",
    "AssetType",
    "HeuristicTableDetector",
    "TableCandidate",
]
