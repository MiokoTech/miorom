import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _escape_po_string(s: str) -> str:
    """Escape special characters for GNU gettext PO format."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r")


def _unescape_po_string(s: str) -> str:
    """Unescape GNU gettext PO string literals."""
    out = []
    i = 0
    length = len(s)
    while i < length:
        if s[i] == "\\" and i + 1 < length:
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "r":
                out.append("\r")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _format_po_field(field_name: str, text: str) -> List[str]:
    """Format a multiline or single-line string into PO format."""
    if "\n" in text:
        lines = [f'{field_name} ""']
        sub_lines = text.split("\n")
        for i, sl in enumerate(sub_lines):
            # Include newline escape if not the last line
            suffix = "\\n" if i < len(sub_lines) - 1 else ""
            escaped = _escape_po_string(sl) + suffix
            lines.append(f'"{escaped}"')
        return lines
    else:
        return [f'{field_name} "{_escape_po_string(text)}"']


@dataclass
class PoEntry:
    """Represents a single gettext PO translation unit."""
    msgid: str
    msgstr: str = ""
    msgctxt: Optional[str] = None
    comments: List[str] = field(default_factory=list)           # # comment
    extracted_comments: List[str] = field(default_factory=list) # #. extracted
    references: List[str] = field(default_factory=list)         # #: reference
    flags: List[str] = field(default_factory=list)              # #, flag


class PoHandler:
    """
    Pure-Python GNU gettext (.po / .pot) Translation Memory Bridge.
    Seamlessly integrates ROM dialogue extraction and repacking with modern
    CAT (Computer-Assisted Translation) platforms like Weblate, Crowdin, and Poedit.
    """

    def __init__(self):
        self.headers: Dict[str, str] = {
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "8bit",
            "MIME-Version": "1.0",
        }
        self.entries: List[PoEntry] = []

    def add_entry(
        self,
        msgid: str,
        msgstr: str = "",
        msgctxt: Optional[str] = None,
        comment: Optional[str] = None,
        extracted_comment: Optional[str] = None,
        reference: Optional[str] = None,
        flags: Optional[List[str]] = None,
    ) -> PoEntry:
        """Add a translation entry to the catalog."""
        entry = PoEntry(
            msgid=msgid,
            msgstr=msgstr,
            msgctxt=msgctxt,
            comments=[comment] if comment else [],
            extracted_comments=[extracted_comment] if extracted_comment else [],
            references=[reference] if reference else [],
            flags=list(flags) if flags else [],
        )
        self.entries.append(entry)
        return entry

    def get_entry(self, msgid: str, msgctxt: Optional[str] = None) -> Optional[PoEntry]:
        """Find an entry matching msgid and optional msgctxt."""
        for e in self.entries:
            if e.msgid == msgid and e.msgctxt == msgctxt:
                return e
        return None

    @classmethod
    def from_string(cls, content: str) -> "PoHandler":
        """Parse a GNU gettext PO formatted string."""
        po = cls()
        lines = content.splitlines()

        cur_comments: List[str] = []
        cur_extracted: List[str] = []
        cur_references: List[str] = []
        cur_flags: List[str] = []
        cur_ctxt: Optional[str] = None
        cur_id: Optional[str] = None
        cur_str: Optional[str] = None

        state = "NONE"  # "CTXT", "ID", "STR"

        def flush_entry():
            nonlocal cur_comments, cur_extracted, cur_references, cur_flags, cur_ctxt, cur_id, cur_str
            if cur_id is not None:
                if cur_id == "" and cur_ctxt is None:
                    # Header entry
                    if cur_str:
                        for hline in cur_str.splitlines():
                            if ":" in hline:
                                k, v = hline.split(":", 1)
                                po.headers[k.strip()] = v.strip()
                else:
                    po.entries.append(
                        PoEntry(
                            msgid=cur_id,
                            msgstr=cur_str or "",
                            msgctxt=cur_ctxt,
                            comments=list(cur_comments),
                            extracted_comments=list(cur_extracted),
                            references=list(cur_references),
                            flags=list(cur_flags),
                        )
                    )
            cur_comments = []
            cur_extracted = []
            cur_references = []
            cur_flags = []
            cur_ctxt = None
            cur_id = None
            cur_str = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                flush_entry()
                state = "NONE"
                continue

            if line.startswith("#."):
                cur_extracted.append(line[2:].strip())
            elif line.startswith("#:"):
                cur_references.append(line[2:].strip())
            elif line.startswith("#,"):
                cur_flags.extend([f.strip() for f in line[2:].split(",")])
            elif line.startswith("#"):
                cur_comments.append(line[1:].strip())

            elif line.startswith("msgctxt "):
                state = "CTXT"
                cur_ctxt = _unescape_po_string(re.findall(r'^msgctxt\s+"(.*)"$', line)[0])

            elif line.startswith("msgid "):
                state = "ID"
                cur_id = _unescape_po_string(re.findall(r'^msgid\s+"(.*)"$', line)[0])

            elif line.startswith("msgstr "):
                state = "STR"
                cur_str = _unescape_po_string(re.findall(r'^msgstr\s+"(.*)"$', line)[0])

            elif line.startswith('"') and line.endswith('"'):
                chunk = _unescape_po_string(line[1:-1])
                if state == "CTXT" and cur_ctxt is not None:
                    cur_ctxt += chunk
                elif state == "ID" and cur_id is not None:
                    cur_id += chunk
                elif state == "STR" and cur_str is not None:
                    cur_str += chunk

        flush_entry()
        return po

    @classmethod
    def from_file(cls, path: str) -> "PoHandler":
        """Load PO file from disk."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return cls.from_string(f.read())

    def to_string(self) -> str:
        """Serialize catalog to GNU gettext PO formatted string."""
        blocks = []

        # 1. Header block
        header_lines = ['msgid ""', 'msgstr ""']
        for k, v in self.headers.items():
            header_lines.append(f'"{k}: {v}\\n"')
        blocks.append("\n".join(header_lines))

        # 2. Entries
        for e in self.entries:
            entry_lines = []
            for c in e.comments:
                entry_lines.append(f"# {c}")
            for ec in e.extracted_comments:
                entry_lines.append(f"#. {ec}")
            for r in e.references:
                entry_lines.append(f"#: {r}")
            if e.flags:
                entry_lines.append(f"#, {', '.join(e.flags)}")

            if e.msgctxt is not None:
                entry_lines.extend(_format_po_field("msgctxt", e.msgctxt))

            entry_lines.extend(_format_po_field("msgid", e.msgid))
            entry_lines.extend(_format_po_field("msgstr", e.msgstr))

            blocks.append("\n".join(entry_lines))

        return "\n\n".join(blocks) + "\n"

    def save(self, path: str):
        """Save PO file to disk."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_string())

    def to_translation_dict(self) -> Dict[str, str]:
        """Return simple dictionary mapping msgid -> msgstr (translated text)."""
        res = {}
        for e in self.entries:
            if e.msgstr:
                res[e.msgid] = e.msgstr
        return res

    def to_contextual_dict(self) -> Dict[Tuple[Optional[str], str], str]:
        """Return dictionary mapping (msgctxt, msgid) -> msgstr."""
        res = {}
        for e in self.entries:
            if e.msgstr:
                res[(e.msgctxt, e.msgid)] = e.msgstr
        return res
