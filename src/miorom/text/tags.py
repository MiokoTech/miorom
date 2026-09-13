import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from miorom.result import MioRomResult


@dataclass
class TagValidationReport(MioRomResult):
    """Report on tag syntax and variable integrity."""
    is_valid: bool
    syntax_errors: List[str] = field(default_factory=list)
    missing_variables: List[str] = field(default_factory=list)
    unknown_tags: List[str] = field(default_factory=list)


class TagSyntaxValidator:
    """
    Pure modular validator for rich-text control tags and bracket syntax.
    """

    TAG_PATTERN = re.compile(r"\[([A-Za-z0-9_:\-]+)\]")

    @classmethod
    def extract_tags(cls, text: str) -> List[str]:
        """Extracts tag identifiers like ['HERO', 'ITEM:1'] from text."""
        return cls.TAG_PATTERN.findall(text)

    @classmethod
    def validate(
        cls,
        text: str,
        allowed_tags: Optional[Set[str]] = None,
    ) -> TagValidationReport:
        """
        Validates bracket balance and tags within a single string.
        """
        errors: List[str] = []
        unknown: List[str] = []

        open_cnt = text.count("[")
        close_cnt = text.count("]")

        if open_cnt != close_cnt:
            errors.append(f"Mismatched brackets: {open_cnt} '[' vs {close_cnt} ']'")

        if "[]" in text:
            errors.append("Empty tag '[]' found")

        tags = cls.extract_tags(text)
        if allowed_tags is not None:
            for t in tags:
                base_t = t.split(":")[0]
                if t not in allowed_tags and base_t not in allowed_tags:
                    unknown.append(t)

        is_valid = (len(errors) == 0) and (len(unknown) == 0)

        return TagValidationReport(
            is_valid=is_valid,
            syntax_errors=errors,
            missing_variables=[],
            unknown_tags=unknown,
        )

    @classmethod
    def validate_pair(
        cls,
        original_text: str,
        translated_text: str,
        variable_prefixes: Sequence[str] = ("NAME", "HERO", "ITEM", "NUM", "VAL", "VAR"),
    ) -> TagValidationReport:
        """
        Validates that dynamic variable tags in original_text are preserved in translated_text.
        """
        base_rep = cls.validate(translated_text)
        orig_tags = cls.extract_tags(original_text)
        trans_tags = cls.extract_tags(translated_text)

        missing_vars: List[str] = []
        for t in orig_tags:
            is_var = any(t.startswith(prefix) for prefix in variable_prefixes)
            if is_var and t not in trans_tags and t not in missing_vars:
                missing_vars.append(t)

        is_valid = base_rep.is_valid and (len(missing_vars) == 0)

        return TagValidationReport(
            is_valid=is_valid,
            syntax_errors=base_rep.syntax_errors,
            missing_variables=missing_vars,
            unknown_tags=base_rep.unknown_tags,
        )


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

