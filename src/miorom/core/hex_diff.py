"""
miorom.core.hex_diff
~~~~~~~~~~~~~~~~~~~~
Visual Terminal Hex Diff Highlighter Primitive.
Generates side-by-side or inline color-coded hex diffs (with ANSI escape codes)
to let reverse engineers visually verify binary writes and patches before committing.
"""

from typing import List, Optional
import logging

logger = logging.getLogger(__name__)



class HexDiffHighlighter:
    """
    Pure primitive to render colorized terminal hex diffs between binary buffers.
    """

    # ANSI escape sequences
    COLOR_RESET = "\033[0m"
    COLOR_CHANGED = "\033[92m"      # Bright Green (modified byte)
    COLOR_OLD = "\033[91m"          # Bright Red (original byte)
    COLOR_OFFSET = "\033[94m"       # Blue (offset)

    @classmethod
    def format_diff(
        cls,
        original: bytes,
        modified: bytes,
        offset: int = 0,
        size: Optional[int] = None,
        bytes_per_line: int = 16,
        use_color: bool = True,
    ) -> str:
        """
        Renders a hex diff string showing original vs modified bytes.
        """
        max_len = max(len(original), len(modified))
        limit = min(max_len - offset, size) if size is not None else (max_len - offset)
        if limit <= 0:
            return "No data to diff."

        lines: List[str] = []
        c_reset = cls.COLOR_RESET if use_color else ""
        c_green = cls.COLOR_CHANGED if use_color else ""
        c_red = cls.COLOR_OLD if use_color else ""
        c_blue = cls.COLOR_OFFSET if use_color else ""

        lines.append(f"{c_blue}OFFSET   | ORIGINAL                         | MODIFIED{c_reset}")
        lines.append("-" * 65)

        for i in range(0, limit, bytes_per_line):
            cur_off = offset + i
            chunk_len = min(bytes_per_line, limit - i)

            orig_hex: List[str] = []
            mod_hex: List[str] = []
            has_diff = False

            for j in range(chunk_len):
                idx = cur_off + j
                b_orig = original[idx] if idx < len(original) else None
                b_mod = modified[idx] if idx < len(modified) else None

                if b_orig == b_mod:
                    s_orig = f"{b_orig:02X}" if b_orig is not None else "  "
                    s_mod = f"{b_mod:02X}" if b_mod is not None else "  "
                else:
                    has_diff = True
                    s_orig = f"{c_red}{b_orig:02X}{c_reset}" if b_orig is not None else "  "
                    s_mod = f"{c_green}{b_mod:02X}{c_reset}" if b_mod is not None else "  "

                orig_hex.append(s_orig)
                mod_hex.append(s_mod)

            marker = "*" if has_diff else " "
            row = (
                f"{c_blue}{cur_off:08X}{c_reset} {marker} "
                f"{' '.join(orig_hex):<30} | {' '.join(mod_hex)}"
            )
            lines.append(row)

        return "\n".join(lines)

    @classmethod
    def print_diff(
        cls,
        original: bytes,
        modified: bytes,
        offset: int = 0,
        size: Optional[int] = None,
        use_color: bool = True,
    ) -> None:
        """Prints the formatted hex diff to standard output."""
        logger.info(cls.format_diff(original, modified, offset, size, use_color=use_color))
