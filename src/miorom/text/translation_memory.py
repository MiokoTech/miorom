"""
miorom.text.translation_memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Translation memory with fuzzy string matching for ROM dialogue workflows.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.result import MioRomResult
from miorom.text.po_handler import PoEntry


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings via dynamic programming."""
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la

    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[lb]


def _similarity(a: str, b: str) -> float:
    """Return similarity score in [0.0, 1.0] based on Levenshtein distance."""
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max_len


@dataclass
class TmMatch(MioRomResult):
    """A single translation memory candidate with its fuzzy match score."""
    source: str
    target: str
    score: float
    is_exact: bool


@dataclass
class TmLookupResult(MioRomResult):
    """Result of a translation memory lookup query."""
    query: str
    matches: List[TmMatch]
    best_match: Optional[TmMatch]


class TranslationMemory:
    """
    In-memory translation memory with Levenshtein-based fuzzy matching.

    Entries are stored as (source, target) pairs. Lookup returns candidates
    scored by string similarity and filtered by a configurable threshold.
    """

    def __init__(self, fuzzy_threshold: float = 0.75) -> None:
        self._fuzzy_threshold = fuzzy_threshold
        self._entries: List[Tuple[str, str]] = []

    def add(self, source: str, target: str) -> None:
        """Add a source/target pair to the translation memory."""
        self._entries.append((source, target))

    def lookup(self, source: str, max_results: int = 5) -> TmLookupResult:
        """Return up to max_results TmMatch objects above the fuzzy threshold."""
        candidates: List[TmMatch] = []

        for src, tgt in self._entries:
            score = _similarity(source, src)
            if score >= self._fuzzy_threshold:
                candidates.append(
                    TmMatch(
                        source=src,
                        target=tgt,
                        score=score,
                        is_exact=(score == 1.0),
                    )
                )

        candidates.sort(key=lambda m: m.score, reverse=True)
        matches = candidates[:max_results]
        best = matches[0] if matches else None

        return TmLookupResult(query=source, matches=matches, best_match=best)

    def pre_fill_po(self, entries: List[PoEntry], flag_fuzzy: bool = True) -> int:
        """
        Fill untranslated PoEntry objects using TM matches.

        Exact matches are applied silently; fuzzy matches receive a
        'fuzzy' flag when flag_fuzzy is True. Returns the count of
        entries that were filled.
        """
        filled = 0
        for entry in entries:
            if entry.msgstr:
                continue
            result = self.lookup(entry.msgid)
            if result.best_match is None:
                continue
            match = result.best_match
            entry.msgstr = match.target
            if not match.is_exact and flag_fuzzy and "fuzzy" not in entry.flags:
                entry.flags.append("fuzzy")
            filled += 1
        return filled

    def export_json(self) -> str:
        """Serialize the translation memory to a JSON string."""
        data = {
            "fuzzy_threshold": self._fuzzy_threshold,
            "entries": [{"source": src, "target": tgt} for src, tgt in self._entries],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "TranslationMemory":
        """Deserialize a TranslationMemory from a JSON string produced by export_json."""
        data = json.loads(json_str)
        tm = cls(fuzzy_threshold=data.get("fuzzy_threshold", 0.75))
        for pair in data.get("entries", []):
            tm.add(pair["source"], pair["target"])
        return tm

    def __len__(self) -> int:
        return len(self._entries)
