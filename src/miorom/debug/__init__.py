"""
miorom.debug - Live Emulator Bridge & Dynamic Analysis.
"""

from miorom.debug.buffer_analyzer import (
    BufferPatcher,
    BufferRiskReport,
    RuntimeBufferAnalyzer,
)
from miorom.debug.client import DolphinClient, DolphinMemoryMock, EmulatorClient
from miorom.debug.gdb_client import GDBEmulatorClient, GDBProtocolMock, StopReason
from miorom.debug.protocols import EmulatorClientProtocol
from miorom.debug.sanitizer import (
    AccessType,
    MemorySanitizerError,
    RomAddressSanitizer,
    SanitizerReport,
    SanitizerViolation,
    ShadowTag,
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
