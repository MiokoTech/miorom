from typing import List, Tuple, Optional


class WordWrapper:
    """
    Simulates game text-wrapping and validates dialogue boxes to prevent text overflow.
    """

    def __init__(self, max_chars_per_line: int = 36, max_lines_per_box: int = 3, newline_tag: str = "<ENTER>"):
        self.max_chars_per_line = max_chars_per_line
        self.max_lines_per_box = max_lines_per_box
        self.newline_tag = newline_tag

    def wrap_text(self, text: str) -> str:
        """
        Auto-wrap a paragraph into lines delimited by newline_tag.
        Preserves existing newlines / newline_tags.
        """
        # Replace tag with actual newline for processing
        normalized = text.replace(self.newline_tag, "\n")
        paragraphs = normalized.split("\n")
        wrapped_lines = []

        for para in paragraphs:
            words = para.split(" ")
            current_line = []
            current_len = 0

            for word in words:
                word_len = len(word)
                if not current_line:
                    current_line.append(word)
                    current_len = word_len
                elif current_len + 1 + word_len <= self.max_chars_per_line:
                    current_line.append(word)
                    current_len += 1 + word_len
                else:
                    wrapped_lines.append(" ".join(current_line))
                    current_line = [word]
                    current_len = word_len

            if current_line:
                wrapped_lines.append(" ".join(current_line))

        return self.newline_tag.join(wrapped_lines)

    def validate_textbox(self, text: str) -> Tuple[bool, List[str]]:
        """
        Check if text exceeds line length or box height.
        Returns (is_valid, list_of_warnings).
        """
        normalized = text.replace(self.newline_tag, "\n")
        lines = normalized.split("\n")
        warnings = []

        if len(lines) > self.max_lines_per_box:
            warnings.append(f"Too many lines: {len(lines)} > {self.max_lines_per_box} lines max")

        for idx, line in enumerate(lines):
            # Ignore tag placeholders when measuring length if needed
            if len(line) > self.max_chars_per_line:
                warnings.append(
                    f"Line {idx+1} exceeds max width: {len(line)} > {self.max_chars_per_line} chars ('{line[:20]}...')"
                )

        return len(warnings) == 0, warnings
