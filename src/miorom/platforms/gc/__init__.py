"""
miorom.platforms.gc - Nintendo GameCube & Wii Optical Disc Engine.
Supports .iso and .gcm disc images, Disc Header parsing, File System Table (FST) manipulation,
file extraction, and compliant disc repacking.
"""

from miorom.platforms.gc.disc import FSTEntry, GameCubeDisc, GCHeader
from miorom.platforms.gc.fst_injector import FstInjector, FstNode

__all__ = [
    "GCHeader",
    "FSTEntry",
    "GameCubeDisc",
    "FstInjector",
    "FstNode",
]
