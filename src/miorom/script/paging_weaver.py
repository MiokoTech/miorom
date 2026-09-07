"""
miorom.script.paging_weaver
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dynamic Script Dialogue Paging Weaver.
Bridges VM bytecode engines with text auto-paginators. When translated dialogue
exceeds physical textbox limits, it automatically weaves VM control opcodes
(e.g. WAIT_BUTTON, CLEAR_TEXTBOX, PAGE_BREAK) into the script instruction stream
so long translations flow seamlessly across pages without manual script splitting.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.text.paginator import SmartAutoPaginator, PaginationConfig
from miorom.text.vwf import GlyphWidthTable


@dataclass
class PagingWeaveConfig:
    """Configuration for dialogue page weaving."""
    paginator: Optional[SmartAutoPaginator] = None
    message_opcode: str = "MESSAGE"
    wait_opcode: Optional[str] = "WAIT_BUTTON"
    clear_opcode: Optional[str] = "CLEAR_BOX"
    speaker_arg_index: Optional[int] = 0
    text_arg_index: int = 1
    page_break_delimiter: str = "[PAGE]"


class SmartScriptPagingWeaver:
    """
    Splits long translated dialogues and weaves VM opcodes into script streams.
    """

    def __init__(
        self,
        config: Optional[PagingWeaveConfig] = None,
        pagination_config: Optional[PaginationConfig] = None,
        glyph_table: Optional[GlyphWidthTable] = None,
    ):
        self.config = config or PagingWeaveConfig()
        if self.config.paginator is None:
            pag_cfg = pagination_config or PaginationConfig(
                page_break_tag=self.config.page_break_delimiter
            )
            self.config.paginator = SmartAutoPaginator(pag_cfg, glyph_table)

    def paginate_string(self, text: str) -> List[str]:
        """
        Paginates text into individual page strings using the configured paginator.
        """
        paginated_full = self.config.paginator.paginate_text(text)
        delim = self.config.page_break_delimiter
        pages = paginated_full.split(delim)
        return [p.strip() for p in pages if p.strip()]

    def weave_dialogue_sequence(
        self,
        text: str,
        speaker: Optional[Any] = None,
    ) -> List[Tuple[str, List[Any]]]:
        """
        Takes a long text and generates a sequence of VM instruction tuples:
        [(MESSAGE, [speaker, page1]), (WAIT_BUTTON, []), (CLEAR_BOX, []), (MESSAGE, [speaker, page2]), ...]
        """
        pages = self.paginate_string(text)
        if not pages:
            pages = [text]

        instructions: List[Tuple[str, List[Any]]] = []
        for i, page in enumerate(pages):
            # Build arguments for MESSAGE
            args: List[Any] = []
            if self.config.speaker_arg_index is not None and speaker is not None:
                if self.config.speaker_arg_index == 0:
                    args.append(speaker)
                    args.append(page)
                else:
                    args.append(page)
                    args.append(speaker)
            else:
                args.append(page)

            instructions.append((self.config.message_opcode, args))

            # Weave intermediate wait/clear opcodes between pages
            if i + 1 < len(pages):
                if self.config.wait_opcode:
                    instructions.append((self.config.wait_opcode, []))
                if self.config.clear_opcode:
                    instructions.append((self.config.clear_opcode, []))

        return instructions

    def weave_text_script(self, script_text: str) -> str:
        """
        Parses a human-readable text script (e.g. from ScriptVM.disassemble),
        finds MESSAGE lines with long dialogues, and weaves paginated opcode blocks.
        """
        msg_op = self.config.message_opcode
        pattern = re.compile(rf"^(\s*){re.escape(msg_op)}\s+(.+)$", re.MULTILINE)

        def replace_line(match: re.Match) -> str:
            indent = match.group(1)
            raw_args = match.group(2).strip()

            # Parse arguments: speaker and quoted string
            # Handles: "Text" or 0x01, "Text" or 1, "Text"
            str_match = re.search(r'"([^"]*)"', raw_args)
            if not str_match:
                return match.group(0)

            orig_str = str_match.group(1)
            before_str = raw_args[: str_match.start()].strip()
            speaker = before_str.rstrip(",").strip() if before_str else None

            # Generate woven instructions
            woven = self.weave_dialogue_sequence(orig_str, speaker=speaker)
            lines: List[str] = []
            for op_name, args in woven:
                if args:
                    fmt_args = []
                    for a in args:
                        if isinstance(a, str):
                            fmt_args.append(f'"{a}"')
                        else:
                            fmt_args.append(str(a))
                    line_str = f"{indent}{op_name} {', '.join(fmt_args)}"
                else:
                    line_str = f"{indent}{op_name}"
                lines.append(line_str)

            return "\n".join(lines)

        return pattern.sub(replace_line, script_text)
