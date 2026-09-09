"""
miorom.debug - Live Emulator Bridge & Dynamic Analysis.
"""

from miorom.debug.client import EmulatorClient, DolphinClient, DolphinMemoryMock
from miorom.debug.protocols import EmulatorClientProtocol
from miorom.debug.gdb_client import GDBEmulatorClient, GDBProtocolMock, StopReason
from miorom.debug.sanitizer import (
    RomAddressSanitizer,
    SanitizerViolation,
    MemorySanitizerError,
    SanitizerReport,
    AccessType,
    ShadowTag,
)
from miorom.debug.buffer_analyzer import (
    RuntimeBufferAnalyzer,
    BufferRiskReport,
    BufferPatcher,
)

__all__ = [
    "DolphinClient",
    "DolphinMemoryMock",
    "EmulatorClient",
    "EmulatorClientProtocol",
    "GDBEmulatorClient",
    "GDBProtocolMock",
    "StopReason",
    "RomAddressSanitizer",
    "SanitizerViolation",
    "MemorySanitizerError",
    "SanitizerReport",
    "AccessType",
    "ShadowTag",
    "RuntimeBufferAnalyzer",
    "BufferRiskReport",
    "BufferPatcher",
]
