"""
miorom.text.tag_validator
~~~~~~~~~~~~~~~~~~~~~~~~~
Pure Tag Syntax & Dynamic Variable Validator Primitive.
Validates bracket balance, detects dangling tags, and ensures translation fidelity
for rich-text game variables without enforcing any translation framework.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import re
from typing import List, Optional, Sequence, Set


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
                # If tag has parameter like ITEM:1, check base tag name
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
