# MioROM Security Guide: Handling Untrusted ROMs & Archives

MioROM is a reverse-engineering library. By design, most of its input is
**untrusted binary data**: ROM dumps and archives from unknown sources
(homebrew, community ROM hacks, third-party translation patches, files
uploaded by other people into tools built on top of MioROM). This guide
covers the security guarantees MioROM makes when extracting that data to
disk, and what's expected of you if you extend MioROM with your own
archive/ROM handler.

---

## 1. Threat model

Any function that writes a file to disk using a **name that came from
inside a ROM/archive** is a potential attack surface. A malicious archive
can embed an entry name such as:

```
../../../home/user/.bashrc
/etc/cron.d/evil
..\..\..\Windows\System32\evil.dll
```

If that name is joined to an output directory with plain
`os.path.join(output_dir, entry_name)` and written without validation, the
resulting file can land **outside** the directory the caller intended —
this is commonly called **path traversal** or **zip-slip**. It's the same
class of vulnerability that affects any tool extracting ZIP/TAR/ISO/ROM
containers, not something specific to MioROM's format handling.

**MioROM's guarantee:** every built-in extractor that derives a filename
from archive/ROM data routes that name through
[`sanitize_extract_path()`](#2-the-fix-sanitize_extract_path) before
touching the filesystem, so extraction can never write outside the
directory you pass in.

---

## 2. The fix: `sanitize_extract_path()`

```python
from miorom.security import sanitize_extract_path, UnsafeArchivePathError

safe_path = sanitize_extract_path(output_dir, entry_name)
```

**Behavior:**
- Resolves `output_dir` to an absolute, symlink-free path (`os.path.realpath`).
- Normalizes the entry name (`\` → `/`) and strips any leading slash, so an
  entry name that *looks* absolute is still confined to `output_dir` rather
  than reinterpreted as a real filesystem root.
- Rejects (`raise UnsafeArchivePathError`) any entry name whose resolved
  path — after following `..` components — would land outside
  `output_dir`.
- Returns the final, safe absolute path on success. This is the **only**
  value that should ever be passed to `open(..., "wb")` when writing
  archive contents.

**`UnsafeArchivePathError`** (subclass of `miorom.errors.MioromError`)
carries structured context for programmatic handling, consistent with
every other MioROM exception (see
[Library Contracts → Structured Exceptions](LIBRARY_CONTRACTS.md)):

```python
try:
    path = sanitize_extract_path(output_dir, entry.name)
except UnsafeArchivePathError as err:
    log.warning(
        "Rejected unsafe entry %r -> %r (outside %r)",
        err.entry_name, err.resolved_path, err.output_dir,
    )
```

| Attribute | Meaning |
| :--- | :--- |
| `err.entry_name` | The raw, unmodified name as it appeared in the archive/ROM. |
| `err.resolved_path` | The absolute path it would have resolved to. |
| `err.output_dir` | The extraction root the caller intended to stay within. |

---

## 3. Where this is applied today

`sanitize_extract_path()` is wired into every built-in extractor that
accepts an entry-supplied name:

| Module | Function | Entry-name source |
| :--- | :--- | :--- |
| `miorom.archive.container` | `ArchiveContainer.extract_to_dir()` | Generic TOC `ArchiveEntry.name` |
| `miorom.archive.dissector` | `DissectedArchive.extract_to_dir()` | Heuristically dissected `ArchiveEntry.name` |
| `miorom.platforms.wii.u8` | `U8Archive.extract_all()` | Wii/GC U8 `entry.path` |
| `miorom.platforms.nds.narc` | `NARCArchive.extract_all()` | NDS NARC FNT filename |

`miorom.archive.toc_pair` and `miorom.compression.carver` are **not** on
this list on purpose — both generate their own output filenames
(`f"{prefix}{index:04d}{ext}"`) rather than trusting a name from the
archive, so there's nothing to sanitize.

---

## 4. Checklist for custom `BaseRomHandler` / archive implementations

If you're extending MioROM with your own ROM/archive handler (see the
[Plugin Guide](PLUGIN_GUIDE.md)) and your `unpack()` writes files whose
names come from parsed data — headers, file tables, TOCs, anything
attacker-influenced — route every write through `sanitize_extract_path()`:

```python
import os
from miorom.security import sanitize_extract_path

class MyConsoleRomHandler(BaseRomHandler):
    name = "myconsole"

    def unpack(self, data: bytes, output_dir: str) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        for entry in self._parse_file_table(data):
            dest = sanitize_extract_path(output_dir, entry.name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(entry.data)
        ...
```

This is the same pattern used by all four built-in extractors in §3 — copy
it rather than reimplementing path joining by hand.

---

## 5. Known limitations / hardening notes

- **Absolute paths are neutralized, not rejected.** An entry name like
  `/etc/passwd` is currently *not* raised as `UnsafeArchivePathError` —
  the leading `/` is stripped and it's treated as the relative path
  `etc/passwd` inside `output_dir`. The result never escapes `output_dir`,
  so this is safe, but it is a silent reinterpretation of attacker-supplied
  input rather than an explicit rejection. If your threat model prefers
  "fail loudly on anything suspicious" over "neutralize and continue",
  add an explicit check for a leading `/` (or a Windows drive letter, e.g.
  `C:\`) at the top of `sanitize_extract_path()` and raise
  `UnsafeArchivePathError` immediately, before the `.lstrip("/")` step.
- **Windows drive letters are not explicitly detected** (`C:\evil.txt`).
  On POSIX this is treated as a harmless relative path segment; on Windows
  it should be tested explicitly if you deploy there.
- **This guide covers extraction (write) safety only.** It does not cover
  decompression-bomb limits (`max_output` on decompressors), which is a
  separate, orthogonal concern — check the decompressor's own
  documentation for output-size guards when processing untrusted
  compressed streams.

---

## 6. Regression tests

`tests/test_security_extract_path.py` covers:
- Rejection of `../`, backslash-style, and nested traversal entry names.
- Normal relative sub-directory names still resolving correctly.
- End-to-end rejection via `ArchiveContainer.extract_to_dir()`, not just
  the raw `sanitize_extract_path()` function.

Run just this suite after touching any extraction code:

```bash
pytest tests/test_security_extract_path.py -v
```
