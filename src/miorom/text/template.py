"""
miorom.text.template
~~~~~~~~~~~~~~~~~~~~
Game Text Dialogue Template & Tag Interpolator Primitive.
Enables bidirectional rendering and parameter extraction for rich-text game
strings with dynamic control tags (e.g., '[HERO]', '[ITEM:{id}]').
"""

import re
from typing import Any, Dict, List, Optional


class GameTextTemplate:
    """
    Template engine for dialogue strings with dynamic tags.
    """

    VAR_PATTERN = re.compile(r"\{([A-Za-z0-9_]+)\}")

    def __init__(self, template: str):
        self.template = template
        self.variables: List[str] = self.VAR_PATTERN.findall(template)

        # Build regex for reverse extraction
        # Escape template literal parts, and replace {var} with capture groups
        escaped = re.escape(template)
        pattern_str = re.sub(r"\\\{([A-Za-z0-9_]+)\\\}", r"(?P<\1>.+?)", escaped)
        self._regex = re.compile(f"^{pattern_str}$")

    def render(self, **kwargs: Any) -> str:
        """
        Substitutes variables in template with keyword arguments.
        """
        result = self.template
        for k, v in kwargs.items():
            result = result.replace(f"{{{k}}}", str(v))
        return result

    def extract(self, rendered_text: str) -> Optional[Dict[str, str]]:
        """
        Extracts variable values from rendered_text.
        Returns dictionary of variable name -> string value, or None if no match.
        """
        m = self._regex.match(rendered_text)
        if not m:
            return None
        return m.groupdict()
