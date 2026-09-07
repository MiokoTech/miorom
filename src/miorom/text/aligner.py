import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class AlignedString:
    index_a: Optional[int]
    string_a: Optional[str]
    pointer_a: Optional[int]
    index_b: Optional[int]
    string_b: Optional[str]
    pointer_b: Optional[int]
    similarity: float

    @property
    def is_exact_match(self) -> bool:
        return self.similarity >= 0.999

    @property
    def is_orphan_a(self) -> bool:
        return self.index_b is None

    @property
    def is_orphan_b(self) -> bool:
        return self.index_a is None


class StringAligner:
    """
    Cross-Version String & Pointer Alignment Engine.
    Aligns dialogue and message tables between different ROM versions/revisions (e.g. JP <-> US, v1.0 <-> v1.1)
    and transfers translation data across versions accurately.
    """

    @classmethod
    def align(
        cls,
        strings_a: List[str],
        strings_b: List[str],
        pointers_a: Optional[List[int]] = None,
        pointers_b: Optional[List[int]] = None,
        min_similarity: float = 0.5,
    ) -> List[AlignedString]:
        """
        Aligns two lists of strings using Longest Common Subsequence (LCS) and fuzzy diffing.
        Preserves relative sequence order and handles insertions/deletions.
        """
        matcher = difflib.SequenceMatcher(None, strings_a, strings_b)
        results: List[AlignedString] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    idx_a = i1 + k
                    idx_b = j1 + k
                    results.append(
                        AlignedString(
                            index_a=idx_a,
                            string_a=strings_a[idx_a],
                            pointer_a=pointers_a[idx_a] if pointers_a and idx_a < len(pointers_a) else None,
                            index_b=idx_b,
                            string_b=strings_b[idx_b],
                            pointer_b=pointers_b[idx_b] if pointers_b and idx_b < len(pointers_b) else None,
                            similarity=1.0,
                        )
                    )
            elif tag == "replace":
                len_a = i2 - i1
                len_b = j2 - j1
                # Try 1-to-1 matching for overlapping range
                common_len = min(len_a, len_b)
                for k in range(common_len):
                    idx_a = i1 + k
                    idx_b = j1 + k
                    sim = difflib.SequenceMatcher(None, strings_a[idx_a], strings_b[idx_b]).ratio()
                    results.append(
                        AlignedString(
                            index_a=idx_a,
                            string_a=strings_a[idx_a],
                            pointer_a=pointers_a[idx_a] if pointers_a and idx_a < len(pointers_a) else None,
                            index_b=idx_b,
                            string_b=strings_b[idx_b],
                            pointer_b=pointers_b[idx_b] if pointers_b and idx_b < len(pointers_b) else None,
                            similarity=sim,
                        )
                    )
                # Leftovers in A
                for k in range(common_len, len_a):
                    idx_a = i1 + k
                    results.append(
                        AlignedString(
                            index_a=idx_a,
                            string_a=strings_a[idx_a],
                            pointer_a=pointers_a[idx_a] if pointers_a and idx_a < len(pointers_a) else None,
                            index_b=None,
                            string_b=None,
                            pointer_b=None,
                            similarity=0.0,
                        )
                    )
                # Leftovers in B
                for k in range(common_len, len_b):
                    idx_b = j1 + k
                    results.append(
                        AlignedString(
                            index_a=None,
                            string_a=None,
                            pointer_a=None,
                            index_b=idx_b,
                            string_b=strings_b[idx_b],
                            pointer_b=pointers_b[idx_b] if pointers_b and idx_b < len(pointers_b) else None,
                            similarity=0.0,
                        )
                    )
            elif tag == "delete":
                for k in range(i2 - i1):
                    idx_a = i1 + k
                    results.append(
                        AlignedString(
                            index_a=idx_a,
                            string_a=strings_a[idx_a],
                            pointer_a=pointers_a[idx_a] if pointers_a and idx_a < len(pointers_a) else None,
                            index_b=None,
                            string_b=None,
                            pointer_b=None,
                            similarity=0.0,
                        )
                    )
            elif tag == "insert":
                for k in range(j2 - j1):
                    idx_b = j1 + k
                    results.append(
                        AlignedString(
                            index_a=None,
                            string_a=None,
                            pointer_a=None,
                            index_b=idx_b,
                            string_b=strings_b[idx_b],
                            pointer_b=pointers_b[idx_b] if pointers_b and idx_b < len(pointers_b) else None,
                            similarity=0.0,
                        )
                    )

        return results

    @classmethod
    def transfer_translations(
        cls,
        alignment: List[AlignedString],
        translations_a: Dict[Any, str],
        by_pointer: bool = False,
    ) -> Dict[Any, str]:
        """
        Transfers translations from Version A to Version B using the alignment mapping.
        """
        transferred: Dict[Any, str] = {}
        for item in alignment:
            if item.index_a is not None and item.index_b is not None:
                src_key = item.pointer_a if by_pointer else item.index_a
                dst_key = item.pointer_b if by_pointer else item.index_b

                if src_key in translations_a and dst_key is not None:
                    transferred[dst_key] = translations_a[src_key]
        return transferred
