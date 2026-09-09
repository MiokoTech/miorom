"""Structural interfaces for project assets without mandatory inheritance."""

from typing import Any, List, Protocol, runtime_checkable

from miorom.formats.csv_handler import TranslationRow


@runtime_checkable
class AssetProtocol(Protocol):
    """A structural asset descriptor accepted by project workflows."""

    id: str
    source: str

    def extract_text(self, context: Any = None) -> List[TranslationRow]:
        ...

    def repack_text(self, rows: List[TranslationRow], context: Any = None) -> bytes:
        ...


@runtime_checkable
class ArchiveProtocol(Protocol):
    """A structural read-only archive resource accepted by Game projects."""

    id: str

    def get_toc(self) -> Any:
        ...
