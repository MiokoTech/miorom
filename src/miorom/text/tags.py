import re
from typing import Dict, List, Tuple, Optional


class TagManager:
    """
    Manages game script control codes and placeholders (e.g., <WARNA>, <PLAYER>, <ENTER>).
    Converts between raw hex/bytecode representation and human-friendly tags.
    """

    def __init__(self, mapping: Optional[Dict[str, str]] = None):
        """
        mapping: dict of {raw_repr: tag_repr}
        e.g.: {"[0xff20]": "<WARNA>", "[0x30e9][0x30b0][0x30ca]": "<PLAYER>"}
        """
        self.raw_to_tag: Dict[str, str] = dict(mapping) if mapping else {}
        self.tag_to_raw: Dict[str, str] = {v: k for k, v in self.raw_to_tag.items()}

    def add_tag(self, raw_repr: str, tag_repr: str) -> "TagManager":
        self.raw_to_tag[raw_repr] = tag_repr
        self.tag_to_raw[tag_repr] = raw_repr
        return self

    def decode_tags(self, text: str, newline_tag: str = "<ENTER>") -> str:
        """Convert raw control codes and newlines to human-readable tags."""
        result = text
        for raw, tag in self.raw_to_tag.items():
            result = result.replace(raw, tag)
        if newline_tag:
            result = result.replace("\n", newline_tag)
            result = result.replace("\\n", newline_tag)
        return result

    def encode_tags(self, text: str, newline_tag: str = "<ENTER>") -> str:
        """Convert human-readable tags back to raw control codes and newlines."""
        result = text
        if newline_tag:
            result = result.replace(newline_tag, "\n")
        for tag, raw in self.tag_to_raw.items():
            result = result.replace(tag, raw)
        return result

    def extract_tags(self, text: str) -> List[str]:
        """Extract all <TAG> elements found in a string."""
        return re.findall(r"<[^>]+>", text)

    def validate_tags(self, original_text: str, translated_text: str) -> Tuple[bool, List[str]]:
        """
        Verify that all tags in original_text are preserved in translated_text.
        Returns (is_valid, list_of_missing_tags).
        """
        orig_tags = self.extract_tags(original_text)
        trans_tags = self.extract_tags(translated_text)

        missing = []
        # Check counts of each tag
        for tag in set(orig_tags):
            if trans_tags.count(tag) < orig_tags.count(tag):
                missing.append(f"Missing tag {tag} (expected {orig_tags.count(tag)}, found {trans_tags.count(tag)})")

        return len(missing) == 0, missing
