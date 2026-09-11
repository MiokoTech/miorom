"""
miorom.project.rules
~~~~~~~~~~~~~~~~~~~~
Declarative rules and constraints for game localization and ROM hacking.
"""

from typing import Dict, List, Optional, Tuple
from miorom.text.wrapper import WordWrapper


class Rule:
    """Namespace for localization and engineering rules."""

    class Textbox:
        """Constraint specifying textbox dimensions and word-wrapping limits."""

        def __init__(
            self,
            max_chars: int = 34,
            max_lines: int = 3,
            ignore_tags: bool = True,
        ):
            self.max_chars = max_chars
            self.max_lines = max_lines
            self.ignore_tags = ignore_tags
            self._wrapper = WordWrapper(max_chars_per_line=max_chars, max_lines_per_box=max_lines)

        def validate(self, text: str) -> Tuple[bool, List[str]]:
            """Validate text against textbox boundaries."""
            return self._wrapper.validate_textbox(text)

        def wrap(self, text: str) -> str:
            """Automatically word-wrap text according to textbox boundaries."""
            return self._wrapper.wrap_text(text)

        def __repr__(self) -> str:
            return f"<Rule.Textbox max_chars={self.max_chars} max_lines={self.max_lines}>"

    class TagMap:
        """Mapping between game-internal binary control codes and human-readable tags."""

        def __init__(self, forward_map: Optional[Dict[str, str]] = None):
            # forward_map: raw -> human_tag
            self.raw_to_tag = forward_map or {}
            self.tag_to_raw = {v: k for k, v in self.raw_to_tag.items()}

        def apply(self, text: str) -> str:
            """Convert raw control codes into human tags."""
            out = text
            for raw, tag in self.raw_to_tag.items():
                out = out.replace(raw, tag)
            return out

        def revert(self, text: str) -> str:
            """Convert human tags back into raw control codes."""
            out = text
            for tag, raw in self.tag_to_raw.items():
                out = out.replace(tag, raw)
            return out

        def __repr__(self) -> str:
            return f"<Rule.TagMap {len(self.raw_to_tag)} tags mapped>"
