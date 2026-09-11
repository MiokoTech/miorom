"""
miorom.text.japanese_charmap
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Japanese Relative Text Search Engine & Automated CharMap (.tbl) Synthesizer.

Automates the reverse engineering of Japanese retro console ROMs (NES, SNES,
Game Boy, GBA, Genesis, PS1) by calculating Gojūon (五十音) syllable intervals,
scanning for multi-word RPG menu consensus, and synthesizing Thingy-compatible
character tables (.tbl / CharMap) with zero manual transcription.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.result import MioRomResult
from miorom.text.charmap import CharMap


# ============================================================================
# Japanese Kana Matrices & Standard Console Encodings
# ============================================================================

# Standard 46 Gojūon (fifty sounds) basic Hiragana
HIRAGANA_BASE = (
    "あいうえお"
    "かきくけこ"
    "さしすせそ"
    "たちつてと"
    "なにぬねの"
    "はひふへほ"
    "まみむめも"
    "やゆよ"
    "らりるれろ"
    "わをん"
)

# Voiced (dakuten) and semi-voiced (handakuten) Hiragana
HIRAGANA_DAKUTEN = (
    "がぎぐげご"
    "ざじずぜぞ"
    "だぢづでど"
    "ばびぶべぼ"
    "ぱぴぷぺぽ"
)

# Small Hiragana (sokuon, yōon)
HIRAGANA_SMALL = "ぁぃぅぇぉっゃゅょ"

# Standard 46 Gojūon basic Katakana
KATAKANA_BASE = (
    "アイウエオ"
    "カキクケコ"
    "サシスセソ"
    "タチツテト"
    "ナニヌネノ"
    "ハヒフヘホ"
    "マミムメモ"
    "ヤユヨ"
    "ラリルレロ"
    "ワヲン"
)

# Voiced (dakuten) and semi-voiced (handakuten) Katakana
KATAKANA_DAKUTEN = (
    "ガギグゲゴ"
    "ザジズゼゾ"
    "ダヂヅデド"
    "バビブベボ"
    "パピプペポ"
)

# Small Katakana
KATAKANA_SMALL = "ァィゥェォッャュョ"

# Common Japanese punctuation and special symbols
PUNCTUATION_SYMBOLS = "ー・。、！？「」… "

# Comprehensive table sequences (base + dakuten + small + punctuation)
HIRAGANA_FULL = HIRAGANA_BASE + HIRAGANA_DAKUTEN + HIRAGANA_SMALL + PUNCTUATION_SYMBOLS
KATAKANA_FULL = KATAKANA_BASE + KATAKANA_DAKUTEN + KATAKANA_SMALL + PUNCTUATION_SYMBOLS

# Half-width Katakana (JIS X 0201 sequence)
HALF_WIDTH_KANA = "｡｢｣､･ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾソﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔユヨﾗﾘﾙﾚﾛﾜﾝﾞﾟ"

# Full-width Latin alphabet and digits
FULLWIDTH_LATIN_UPPER = "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
FULLWIDTH_LATIN_LOWER = "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
FULLWIDTH_DIGITS = "０１２３４５６７８９"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class JapaneseWordMatch(MioRomResult):
    """
    Represents a discovered word match in a binary buffer via Japanese relative search.
    """
    word: str
    offset: int
    matched_bytes: bytes
    base_delta: int
    ordering_name: str
    mode: str = "1byte"

    @property
    def offset_hex(self) -> str:
        """Hexadecimal representation of the match offset."""
        return f"0x{self.offset:08X}"


@dataclass
class JapaneseMiningCluster(MioRomResult):
    """
    Consensus cluster of multiple Japanese words sharing the same base encoding delta.
    High confidence (>0.90) indicates an authentic discovered character table.
    """
    base_delta: int
    ordering_name: str
    matches: List[JapaneseWordMatch]
    confidence: float
    min_offset: int
    max_offset: int
    mode: str = "1byte"
    katakana_base_delta: Optional[int] = None
    charmap: Optional[CharMap] = None

    @property
    def unique_word_count(self) -> int:
        """Number of unique words agreeing on this base delta."""
        return len(set(m.word for m in self.matches))

    def build_charmap(
        self,
        include_katakana: bool = True,
        include_latin: bool = True,
        include_digits: bool = True,
        include_punctuation: bool = True,
    ) -> CharMap:
        """
        Synthesizes a full CharMap instance based on this cluster's detected parameters.
        """
        cm = CharMap()
        tbl_content = self.to_tbl(
            include_katakana=include_katakana,
            include_latin=include_latin,
            include_digits=include_digits,
            include_punctuation=include_punctuation,
        )
        for line in tbl_content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            hex_part, char_part = line.split("=", 1)
            try:
                raw = bytes.fromhex(hex_part.strip())
                cm.add_mapping(raw, char_part)
            except ValueError:
                continue

        self.charmap = cm
        return cm

    def to_tbl(
        self,
        include_katakana: bool = True,
        include_latin: bool = True,
        include_digits: bool = True,
        include_punctuation: bool = True,
    ) -> str:
        """
        Exports the synthesized table in standard Thingy .tbl format (HEX=CHAR).
        """
        mappings: Dict[bytes, str] = {}
        mask = 0xFF if self.mode == "1byte" else 0xFFFF

        def format_val(val: int) -> bytes:
            v = val & mask
            if self.mode == "1byte":
                return bytes([v])
            elif self.mode == "2byte_le":
                return struct.pack("<H", v)
            else:  # 2byte_be
                return struct.pack(">H", v)

        # 1. Primary ordering (usually Hiragana)
        if "hiragana" in self.ordering_name:
            primary_chars = HIRAGANA_FULL if include_punctuation else (HIRAGANA_BASE + HIRAGANA_DAKUTEN + HIRAGANA_SMALL)
            for idx, c in enumerate(primary_chars):
                mappings[format_val(self.base_delta + idx)] = c

            # 2. Katakana mapping
            if include_katakana:
                k_base = self.katakana_base_delta
                if k_base is None:
                    # Default: Katakana follows Hiragana continuously or at a 0x50 shift
                    k_base = (self.base_delta + len(primary_chars)) & mask

                k_chars = KATAKANA_FULL if include_punctuation else (KATAKANA_BASE + KATAKANA_DAKUTEN + KATAKANA_SMALL)
                for idx, c in enumerate(k_chars):
                    mappings[format_val(k_base + idx)] = c

        elif "katakana" in self.ordering_name:
            primary_chars = KATAKANA_FULL if include_punctuation else (KATAKANA_BASE + KATAKANA_DAKUTEN + KATAKANA_SMALL)
            for idx, c in enumerate(primary_chars):
                mappings[format_val(self.base_delta + idx)] = c

            # Optional Hiragana mapping if base delta is known
            if self.katakana_base_delta is not None:
                h_chars = HIRAGANA_FULL if include_punctuation else (HIRAGANA_BASE + HIRAGANA_DAKUTEN + HIRAGANA_SMALL)
                for idx, c in enumerate(h_chars):
                    mappings[format_val(self.katakana_base_delta + idx)] = c

        # 3. Latin alphabet and digits (if requested)
        if include_latin:
            # Common ASCII Latin placement or extrapolated sequentially
            latin_base = (max((int.from_bytes(k, "big" if "be" in self.mode else "little") for k in mappings), default=self.base_delta) + 1) & mask
            for idx, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                b = format_val(latin_base + idx)
                if b not in mappings:
                    mappings[b] = c
            latin_lower_base = (latin_base + 26) & mask
            for idx, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
                b = format_val(latin_lower_base + idx)
                if b not in mappings:
                    mappings[b] = c

        if include_digits:
            digit_base = (max((int.from_bytes(k, "big" if "be" in self.mode else "little") for k in mappings), default=self.base_delta) + 1) & mask
            for idx, c in enumerate("0123456789"):
                b = format_val(digit_base + idx)
                if b not in mappings:
                    mappings[b] = c

        # Generate sorted .tbl lines
        lines: List[str] = [
            f"# MioROM Auto-Synthesized Japanese CharMap",
            f"# Ordering: {self.ordering_name}, Base Delta: 0x{self.base_delta:04X}, Mode: {self.mode}",
            f"# Confidence: {self.confidence:.2%}, Consensus Words: {self.unique_word_count}",
        ]
        for raw_bytes, char in sorted(mappings.items(), key=lambda item: item[0]):
            hex_str = raw_bytes.hex().upper()
            lines.append(f"{hex_str}={char}")

        return "\n".join(lines)

    def decode_preview(self, data: bytes, offset: Optional[int] = None, length: int = 128) -> str:
        """
        Decodes a sample slice of the ROM around this cluster using the synthesized CharMap.
        """
        if self.charmap is None:
            self.build_charmap()

        start = self.min_offset if offset is None else offset
        end = min(len(data), start + length)
        slice_data = data[start:end]
        return self.charmap.decode(slice_data)


# ============================================================================
# Mining Engine
# ============================================================================

class JapaneseCharMapMiner:
    """
    Automated Japanese CharMap & Relative Search Engine.
    Discovers custom character tables in retro ROMs by analyzing Gojūon Kana
    relative distances and correlating multi-word consensus across RPG menus.
    """

    DEFAULT_KEYWORDS: Tuple[str, ...] = (
        "たたかう",   # Fight / Attack
        "まほう",     # Magic
        "アイテム",   # Item
        "にげる",     # Run / Flee
        "そうび",     # Equip
        "つよさ",     # Status / Strength
        "ぼうぎょ",   # Defend
        "しらべる",   # Check / Inspect
        "はなす",     # Talk
        "かいふく",   # Recover / Heal
        "ポーション", # Potion
        "セーブ",     # Save
        "やくそう",   # Herb
        "どく",       # Poison
    )

    ORDERINGS: Dict[str, str] = {
        "hiragana_gojuon": HIRAGANA_FULL,
        "hiragana_base": HIRAGANA_BASE,
        "katakana_gojuon": KATAKANA_FULL,
        "katakana_base": KATAKANA_BASE,
        "half_width_kana": HALF_WIDTH_KANA,
    }

    @classmethod
    def search_kana_word(
        cls,
        data: bytes,
        word: str,
        ordering: str = "hiragana_gojuon",
        mode: str = "1byte",
        max_matches: Optional[int] = None,
    ) -> List[JapaneseWordMatch]:
        """
        Performs relative search for a single Japanese word using a specific Kana ordering.

        Args:
            data: Binary ROM buffer.
            word: Japanese search string (e.g. 'たたかう' or 'アイテム').
            ordering: Name of the ordering table ('hiragana_gojuon', 'katakana_gojuon', etc.).
            mode: Search mode: '1byte', '2byte_be', or '2byte_le'.
            max_matches: Maximum matches to return.
        """
        if len(word) < 2:
            return []

        ordering_chars = cls.ORDERINGS.get(ordering)
        if not ordering_chars:
            raise ValueError(f"Unknown Japanese Kana ordering: '{ordering}'")

        # Map each character in the word to its index in the ordering
        indices: List[int] = []
        for c in word:
            if c not in ordering_chars:
                # Word cannot be completely represented in this ordering
                return []
            indices.append(ordering_chars.index(c))

        data_len = len(data)
        matches: List[JapaneseWordMatch] = []

        if mode == "1byte":
            q_len = len(indices)
            deltas = [(indices[i + 1] - indices[i]) & 0xFF for i in range(q_len - 1)]

            for i in range(0, data_len - q_len + 1):
                match = True
                for idx in range(q_len - 1):
                    diff = (data[i + idx + 1] - data[i + idx]) & 0xFF
                    if diff != deltas[idx]:
                        match = False
                        break

                if match:
                    base_delta = (data[i] - indices[0]) & 0xFF
                    matched_bytes = bytes(data[i : i + q_len])
                    matches.append(
                        JapaneseWordMatch(
                            word=word,
                            offset=i,
                            matched_bytes=matched_bytes,
                            base_delta=base_delta,
                            ordering_name=ordering,
                            mode="1byte",
                        )
                    )
                    if max_matches is not None and len(matches) >= max_matches:
                        return matches

        elif mode in ("2byte", "2byte_be", "2byte_le"):
            is_le = mode == "2byte_le"
            fmt = "<H" if is_le else ">H"
            q_len = len(indices)
            deltas = [(indices[i + 1] - indices[i]) & 0xFFFF for i in range(q_len - 1)]

            # Step by 2 (16-bit word alignment)
            for i in range(0, data_len - (q_len * 2) + 1, 2):
                first_val = struct.unpack_from(fmt, data, i)[0]
                cur_val = first_val
                match = True

                for idx in range(q_len - 1):
                    next_val = struct.unpack_from(fmt, data, i + (idx + 1) * 2)[0]
                    diff = (next_val - cur_val) & 0xFFFF
                    if diff != deltas[idx]:
                        match = False
                        break
                    cur_val = next_val

                if match:
                    base_delta = (first_val - indices[0]) & 0xFFFF
                    matched_bytes = bytes(data[i : i + q_len * 2])
                    matches.append(
                        JapaneseWordMatch(
                            word=word,
                            offset=i,
                            matched_bytes=matched_bytes,
                            base_delta=base_delta,
                            ordering_name=ordering,
                            mode=mode,
                        )
                    )
                    if max_matches is not None and len(matches) >= max_matches:
                        return matches

        return matches

    @classmethod
    def mine_charmap(
        cls,
        data: bytes,
        dictionary: Optional[Sequence[str]] = None,
        orderings: Optional[Sequence[str]] = None,
        min_consensus: int = 2,
        proximity_limit: int = 65536,
        mode: str = "1byte",
    ) -> List[JapaneseMiningCluster]:
        """
        Scans a ROM buffer using a dictionary of Japanese menu keywords.
        Groups matches sharing the same base delta within proximity_limit,
        calculating confidence and filtering out false positives.

        Args:
            data: Binary ROM buffer.
            dictionary: List of Japanese words to search. Defaults to DEFAULT_KEYWORDS.
            orderings: Kana ordering schemes to test. Defaults to Hiragana & Katakana.
            min_consensus: Minimum number of distinct words required to form a valid cluster.
            proximity_limit: Maximum byte distance between matches to group into one cluster.
            mode: '1byte', '2byte_be', or '2byte_le'.
        """
        words = list(dictionary) if dictionary is not None else list(cls.DEFAULT_KEYWORDS)
        active_orderings = list(orderings) if orderings is not None else ["hiragana_gojuon", "katakana_gojuon"]

        all_matches: List[JapaneseWordMatch] = []
        for ordering in active_orderings:
            for word in words:
                found = cls.search_kana_word(data, word, ordering=ordering, mode=mode)
                all_matches.extend(found)

        if not all_matches:
            return []

        # Group matches by (ordering_name, base_delta)
        delta_groups: Dict[Tuple[str, int], List[JapaneseWordMatch]] = {}
        for m in all_matches:
            key = (m.ordering_name, m.base_delta)
            delta_groups.setdefault(key, []).append(m)

        clusters: List[JapaneseMiningCluster] = []

        for (ordering, base_delta), group_matches in delta_groups.items():
            # Sort matches by offset to partition into spatial clusters
            group_matches.sort(key=lambda x: x.offset)

            # Sub-partition by proximity limit
            current_sub: List[JapaneseWordMatch] = []
            for m in group_matches:
                if not current_sub:
                    current_sub.append(m)
                else:
                    if m.offset - current_sub[-1].offset <= proximity_limit:
                        current_sub.append(m)
                    else:
                        cls._evaluate_and_add_cluster(clusters, current_sub, ordering, base_delta, min_consensus, mode)
                        current_sub = [m]

            if current_sub:
                cls._evaluate_and_add_cluster(clusters, current_sub, ordering, base_delta, min_consensus, mode)

        # Correlate Hiragana clusters with nearby Katakana
        for h_cl in clusters:
            if "hiragana" in h_cl.ordering_name:
                for m in all_matches:
                    if "katakana" in m.ordering_name and abs(h_cl.min_offset - m.offset) <= proximity_limit:
                        h_cl.katakana_base_delta = m.base_delta
                        h_cl.confidence = min(0.999, h_cl.confidence + 0.03)
                        break

        # Sort clusters by confidence and match count
        clusters.sort(key=lambda c: (c.confidence, len(c.matches)), reverse=True)
        return clusters

    @classmethod
    def _evaluate_and_add_cluster(
        cls,
        dest: List[JapaneseMiningCluster],
        matches: List[JapaneseWordMatch],
        ordering: str,
        base_delta: int,
        min_consensus: int,
        mode: str,
    ) -> None:
        unique_words = len(set(m.word for m in matches))
        if unique_words < min_consensus:
            return

        # Match count confidence scaling
        if unique_words == 1:
            confidence = 0.60
        elif unique_words == 2:
            confidence = 0.95
        elif unique_words == 3:
            confidence = 0.98
        else:
            confidence = min(0.999, 0.98 + (unique_words - 3) * 0.005)

        cluster = JapaneseMiningCluster(
            base_delta=base_delta,
            ordering_name=ordering,
            matches=matches,
            confidence=round(confidence, 4),
            min_offset=min(m.offset for m in matches),
            max_offset=max(m.offset for m in matches),
            mode=mode,
        )
        dest.append(cluster)

    @classmethod
    def auto_discover_and_build(
        cls,
        data: bytes,
        dictionary: Optional[Sequence[str]] = None,
        min_consensus: int = 2,
        mode: str = "1byte",
    ) -> Optional[JapaneseMiningCluster]:
        """
        One-shot automated reverse engineering entry point.
        Discovers the highest-confidence Japanese character encoding in the ROM,
        builds the corresponding CharMap, and returns the populated cluster.
        """
        clusters = cls.mine_charmap(
            data=data,
            dictionary=dictionary,
            min_consensus=min_consensus,
            mode=mode,
        )
        if not clusters:
            return None

        best_cluster = clusters[0]
        best_cluster.build_charmap()
        return best_cluster
