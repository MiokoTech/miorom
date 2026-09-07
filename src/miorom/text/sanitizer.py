"""
miorom.text.sanitizer
~~~~~~~~~~~~~~~~~~~~~
Rich-Text Control Tag & Dynamic Variable Integrity Sanitizer.
Ensures translated dialogue lines preserve essential game variables ([NAME],
[ITEM:X], [NUM:X], [COLOR:X]) and validates balanced bracket syntax to prevent
text engine crashes or garbage character rendering at runtime.
"""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple

from miorom.text.po_handler import PoHandler, PoEntry


@dataclass
class TagValidationResult:
    """Result of control tag integrity check on a translated string."""
    is_valid: bool
    missing_tags: List[str] = field(default_factory=list)
    unexpected_tags: List[str] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)


class ControlTagSanitizer:
    """
    Validates and cleans rich-text tags within dialogue strings.
    """

    TAG_REGEX = re.compile(r"\[([A-Za-z0-9_:\-]+)\]")

    @classmethod
    def extract_tags(cls, text: str) -> List[str]:
        """Extracts all control tags found in the text in order."""
        return cls.TAG_REGEX.findall(text)

    @classmethod
    def check_syntax(cls, text: str) -> List[str]:
        """Checks for unclosed or mismatched bracket characters."""
        errors: List[str] = []
        open_count = text.count("[")
        close_count = text.count("]")

        if open_count != close_count:
            errors.append(f"Mismatched brackets: {open_count} '[' vs {close_count} ']'")

        # Check for empty brackets "[]"
        if "[]" in text:
            errors.append("Empty tag '[]' detected")

        return errors

    @classmethod
    def validate_translation(
        cls,
        original_text: str,
        translated_text: str,
        strict_variable_preservation: bool = True,
    ) -> TagValidationResult:
        """
        Validates that translated_text maintains the control tags and variables of original_text.
        """
        syntax_errs = cls.check_syntax(translated_text)

        orig_tags = cls.extract_tags(original_text)
        trans_tags = cls.extract_tags(translated_text)

        missing: List[str] = []
        if strict_variable_preservation:
            # Check variables like [NAME], [ITEM:0]
            for t in orig_tags:
                if t not in trans_tags and t not in missing:
                    missing.append(t)

        unexpected: List[str] = []
        for t in trans_tags:
            if t not in orig_tags and t not in unexpected:
                unexpected.append(t)

        is_valid = (len(syntax_errs) == 0) and (len(missing) == 0)

        return TagValidationResult(
            is_valid=is_valid,
            missing_tags=missing,
            unexpected_tags=unexpected,
            syntax_errors=syntax_errs,
        )

    @classmethod
    def sanitize(cls, text: str) -> str:
        """
        Cleans common translator typos:
        - Spaces inside brackets: [ HERO ] -> [HERO]
        - Double brackets: [[HERO]] -> [HERO]
        """
        cleaned = re.sub(r"\[\s+([A-Za-z0-9_:\-]+)\s+\]", r"[\1]", text)
        cleaned = re.sub(r"\[\[+([A-Za-z0-9_:\-]+)\]\]+", r"[\1]", cleaned)
        return cleaned

    @classmethod
    def lint_po_catalog(cls, po_handler: PoHandler) -> List[Dict[str, Any]]:
        """
        Scans a complete gettext PO translation catalog and returns all problematic entries.
        """
        issues: List[Dict[str, Any]] = []
        for idx, entry in enumerate(po_handler.entries):
            if not entry.msgstr:
                continue

            res = cls.validate_translation(entry.msgid, entry.msgstr)
            if not res.is_valid:
                issues.append({
                    "entry_index": idx,
                    "msgid": entry.msgid,
                    "msgstr": entry.msgstr,
                    "missing_tags": res.missing_tags,
                    "syntax_errors": res.syntax_errors,
                })

        return issues
