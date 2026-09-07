from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseRomHandler(ABC):
    """
    Abstract base class for format-specific ROM unpackers and repackers.
    """

    name: str = "base"
    description: str = "Base ROM handler"
    extensions: list = []

    @abstractmethod
    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        """Returns True if this handler can parse the given binary data or file."""
        pass

    @abstractmethod
    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        """
        Unpacks ROM binary into destination output directory.
        Returns a dictionary containing metadata to be written into miorom.meta.json.
        """
        pass

    @abstractmethod
    def repack(self, input_dir: str, **kwargs) -> bytes:
        """
        Reads unpacked ROM directory and repacks it into compliant binary data.
        """
        pass
