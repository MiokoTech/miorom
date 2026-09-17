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
from miorom.scanner.crypto import CryptoMatch, CryptoReport, CryptoScanner
from miorom.scanner.deep import (
    BinaryFingerprint,
    DeepScanner,
    DeepScanReport,
    calculate_block_entropy,
    calculate_entropy,
)
from miorom.scanner.inspector import (
    EncodingCandidate,
    InspectionReport,
    SmartInspector,
)
from miorom.scanner.pattern import AOBPatternScanner, CompiledPattern, PatternMatch
from miorom.scanner.table_detector import HeuristicTableDetector, TableCandidate
from miorom.scanner.text_stream import TextStreamScanner, TextStreamSpan
from miorom.scanner.triage import AssetType, FileTriageRecord, RomTriageEngine, TriageReport
from miorom.scanner.xref import XRefAnalyzer, XRefEntry, XRefGraph, XRefType

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
    "TextStreamScanner",
    "TextStreamSpan",
]
