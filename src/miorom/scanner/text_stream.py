"""
miorom.scanner.text_stream
~~~~~~~~~~~~~~~~~~~~~~~~~~
Multi-byte binary text stream scanner and encoding validator for retro console ROMs.
Scans unmapped ROM blobs for embedded dialogue, script blocks, and string tables
encoded in Shift-JIS, EUC-JP, UTF-16, or ASCII without requiring external charmaps.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from miorom.result import MioRomResult


@dataclass
class TextStreamSpan(MioRomResult):
    """Represents a validated continuous text span detected within a binary blob."""
    start: int
    end: int
    encoding: str
    length: int
    char_count: int
    confidence: float
    raw_bytes: bytes
    text: str
    kanji_count: int = 0
    kana_count: int = 0
    is_null_terminated: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class TextStreamScanner:
    """
    Binary scanner identifying structured multi-byte and single-byte string sequences.
    Applies strict lead-byte and trail-byte FSM validation to eliminate false positives
    from machine code and compressed streams.
    """

    SJIS_LEAD_STANDARD = range(0x81, 0xA0)
    SJIS_LEAD_EXTENDED = range(0xE0, 0xFD)
    SJIS_TRAIL_RANGE1 = range(0x40, 0x7F)
    SJIS_TRAIL_RANGE2 = range(0x80, 0xFD)
    SJIS_HALFWIDTH_KANA = range(0xA1, 0xE0)

    EUC_JP_KANJI = range(0xA1, 0xFF)
    EUC_JP_SS2 = 0x8E

    COMMON_ASCII_PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

    def __init__(
        self,
        min_length: int = 4,
        min_confidence: float = 0.65,
        allowed_control_bytes: Optional[Set[int]] = None,
    ):
        self.min_length = min_length
        self.min_confidence = min_confidence
        self.allowed_control_bytes = allowed_control_bytes or {0x00, 0x0A, 0x0D}

    @classmethod
    def is_valid_sjis_lead(cls, byte: int) -> bool:
        """Checks if byte falls within Shift-JIS double-byte lead range."""
        return byte in cls.SJIS_LEAD_STANDARD or byte in cls.SJIS_LEAD_EXTENDED

    @classmethod
    def is_valid_sjis_trail(cls, byte: int) -> bool:
        """Checks if byte falls within Shift-JIS double-byte trail range."""
        return byte in cls.SJIS_TRAIL_RANGE1 or byte in cls.SJIS_TRAIL_RANGE2

    @classmethod
    def is_sjis_halfwidth_kana(cls, byte: int) -> bool:
        """Checks if byte is a standard single-byte halfwidth katakana."""
        return byte in cls.SJIS_HALFWIDTH_KANA

    def validate_sjis_stream(self, data: bytes, start_pos: int) -> Tuple[int, int, int, int, bool]:
        """
        Parses continuous Shift-JIS stream starting at start_pos.
        Returns (bytes_consumed, char_count, kanji_count, kana_count, is_terminated).
        """
        pos = start_pos
        total_len = len(data)
        chars = 0
        kanji = 0
        kana = 0
        terminated = False

        while pos < total_len:
            b = data[pos]

            if b == 0x00:
                terminated = True
                break

            if b in self.COMMON_ASCII_PRINTABLE:
                chars += 1
                pos += 1
                continue

            if self.is_sjis_halfwidth_kana(b):
                chars += 1
                kana += 1
                pos += 1
                continue

            if self.is_valid_sjis_lead(b):
                if pos + 1 < total_len and self.is_valid_sjis_trail(data[pos + 1]):
                    chars += 1
                    b2 = data[pos + 1]
                    sjis_code = (b << 8) | b2
                    if 0x829F <= sjis_code <= 0x8396:
                        kana += 1
                    elif 0x889F <= sjis_code <= 0x9FFC or 0xE040 <= sjis_code <= 0xEA40:
                        kanji += 1
                    pos += 2
                    continue
                break

            break

        bytes_consumed = pos - start_pos
        return bytes_consumed, chars, kanji, kana, terminated

    def validate_euc_jp_stream(self, data: bytes, start_pos: int) -> Tuple[int, int, int, int, bool]:
        """
        Parses continuous EUC-JP stream starting at start_pos.
        Returns (bytes_consumed, char_count, kanji_count, kana_count, is_terminated).
        """
        pos = start_pos
        total_len = len(data)
        chars = 0
        kanji = 0
        kana = 0
        terminated = False

        while pos < total_len:
            b = data[pos]

            if b == 0x00:
                terminated = True
                break

            if b in self.COMMON_ASCII_PRINTABLE:
                chars += 1
                pos += 1
                continue

            if b == self.EUC_JP_SS2:
                if pos + 1 < total_len and data[pos + 1] in self.SJIS_HALFWIDTH_KANA:
                    chars += 1
                    kana += 1
                    pos += 2
                    continue
                break

            if b in self.EUC_JP_KANJI:
                if pos + 1 < total_len and data[pos + 1] in self.EUC_JP_KANJI:
                    chars += 1
                    euc_code = (b << 8) | data[pos + 1]
                    if 0xA4A1 <= euc_code <= 0xA5F6:
                        kana += 1
                    elif 0xB0A1 <= euc_code <= 0xFEFE:
                        kanji += 1
                    pos += 2
                    continue
                break

            break

        bytes_consumed = pos - start_pos
        return bytes_consumed, chars, kanji, kana, terminated

    def validate_utf16_stream(
        self, data: bytes, start_pos: int, big_endian: bool = False
    ) -> Tuple[int, int, int, int, bool]:
        """
        Parses continuous UTF-16 stream.
        Returns (bytes_consumed, char_count, kanji_count, kana_count, is_terminated).
        """
        pos = start_pos
        total_len = len(data)
        chars = 0
        kanji = 0
        kana = 0
        terminated = False

        while pos + 1 < total_len:
            b0 = data[pos]
            b1 = data[pos + 1]
            code = (b0 << 8) | b1 if big_endian else (b1 << 8) | b0

            if code == 0x0000:
                terminated = True
                break

            if not big_endian and b0 == 0x00 and (0x20 <= b1 <= 0x7E):
                break
            if big_endian and b1 == 0x00 and (0x20 <= b0 <= 0x7E):
                break

            if 0x0020 <= code <= 0x007E or code in (0x000A, 0x000D, 0x0009):
                chars += 1
                pos += 2
                continue

            if 0x3040 <= code <= 0x30FF or 0xFF65 <= code <= 0xFF9F:
                chars += 1
                kana += 1
                pos += 2
                continue

            if 0x4E00 <= code <= 0x9FAF:
                chars += 1
                kanji += 1
                pos += 2
                continue

            break

        bytes_consumed = pos - start_pos
        return bytes_consumed, chars, kanji, kana, terminated

    def calculate_confidence(
        self,
        encoding: str,
        length: int,
        char_count: int,
        kanji_count: int,
        kana_count: int,
        is_terminated: bool,
    ) -> float:
        """
        Calculates heuristic confidence score for a candidate text span.
        High ratio of recognized Japanese kana/kanji and standard termination increases confidence.
        """
        if char_count < self.min_length:
            return 0.0

        score = 0.5

        if is_terminated:
            score += 0.15

        if encoding in ("sjis", "euc_jp"):
            japanese_chars = kanji_count + kana_count
            if japanese_chars > 0:
                ratio = japanese_chars / char_count
                score += min(0.35, ratio * 0.4)
            else:
                score += 0.05
        elif "utf-16" in encoding:
            if kanji_count + kana_count > 0:
                score += 0.3
            else:
                score += 0.15
        elif encoding == "ascii":
            if char_count >= 8:
                score += 0.25
            else:
                score += 0.1

        if length >= 16:
            score += 0.05

        return min(1.0, max(0.0, score))

    def scan(
        self,
        data: bytes,
        encodings: Optional[List[str]] = None,
        min_length: Optional[int] = None,
        min_confidence: Optional[float] = None,
    ) -> List[TextStreamSpan]:
        """
        Scans binary data for continuous text spans matching requested encodings.
        """
        target_encodings = [e.lower() for e in (encodings or ["sjis", "euc_jp", "ascii"])]
        min_len = min_length if min_length is not None else self.min_length
        min_conf = min_confidence if min_confidence is not None else self.min_confidence

        results: List[TextStreamSpan] = []
        pos = 0
        total_len = len(data)

        while pos < total_len:
            best_match: Optional[TextStreamSpan] = None

            for enc in target_encodings:
                if enc in ("sjis", "shift_jis", "cp932"):
                    consumed, chars, kanji, kana, term = self.validate_sjis_stream(data, pos)
                    actual_enc = "sjis"
                    codec_name = "shift_jis"
                elif enc in ("euc_jp", "eucjp"):
                    consumed, chars, kanji, kana, term = self.validate_euc_jp_stream(data, pos)
                    actual_enc = "euc_jp"
                    codec_name = "euc_jp"
                elif enc in ("utf-16le", "utf16le"):
                    consumed, chars, kanji, kana, term = self.validate_utf16_stream(data, pos, big_endian=False)
                    actual_enc = "utf-16le"
                    codec_name = "utf-16le"
                elif enc in ("utf-16be", "utf16be"):
                    consumed, chars, kanji, kana, term = self.validate_utf16_stream(data, pos, big_endian=True)
                    actual_enc = "utf-16be"
                    codec_name = "utf-16be"
                elif enc == "ascii":
                    consumed, chars, kanji, kana, term = self.validate_sjis_stream(data, pos)
                    if kanji > 0 or kana > 0:
                        consumed = 0
                    actual_enc = "ascii"
                    codec_name = "ascii"
                else:
                    continue

                if chars >= min_len:
                    conf = self.calculate_confidence(actual_enc, consumed, chars, kanji, kana, term)
                    if conf >= min_conf:
                        raw_chunk = data[pos : pos + consumed]
                        try:
                            decoded_str = raw_chunk.decode(codec_name, errors="replace")
                        except Exception:
                            decoded_str = str(raw_chunk)

                        span = TextStreamSpan(
                            start=pos,
                            end=pos + consumed,
                            encoding=actual_enc,
                            length=consumed,
                            char_count=chars,
                            confidence=conf,
                            raw_bytes=raw_chunk,
                            text=decoded_str,
                            kanji_count=kanji,
                            kana_count=kana,
                            is_null_terminated=term,
                        )

                        if best_match is None or span.confidence > best_match.confidence:
                            best_match = span

            if best_match is not None:
                results.append(best_match)
                skip = best_match.length
                if best_match.is_null_terminated:
                    skip += 2 if "utf-16" in best_match.encoding else 1
                pos += max(1, skip)
            else:
                pos += 1

        return results

    def scan_string_table(
        self,
        data: bytes,
        encodings: Optional[List[str]] = None,
        min_strings: int = 3,
        max_gap: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Detects clusters of text spans forming sequential dialogue or string tables.
        """
        spans = self.scan(data, encodings=encodings)
        if not spans:
            return []

        tables: List[Dict[str, Any]] = []
        current_cluster: List[TextStreamSpan] = []

        for span in spans:
            if not current_cluster:
                current_cluster.append(span)
                continue

            prev = current_cluster[-1]
            gap = span.start - prev.end

            if 0 <= gap <= max_gap and span.encoding == prev.encoding:
                current_cluster.append(span)
            else:
                if len(current_cluster) >= min_strings:
                    tables.append({
                        "start": current_cluster[0].start,
                        "end": current_cluster[-1].end,
                        "encoding": current_cluster[0].encoding,
                        "count": len(current_cluster),
                        "spans": list(current_cluster),
                    })
                current_cluster = [span]

        if len(current_cluster) >= min_strings:
            tables.append({
                "start": current_cluster[0].start,
                "end": current_cluster[-1].end,
                "encoding": current_cluster[0].encoding,
                "count": len(current_cluster),
                "spans": list(current_cluster),
            })

        return tables
