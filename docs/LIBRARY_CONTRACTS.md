# Library Contracts

This document defines the primitive contracts for programmers assembling
their own pipelines on top of MioROM.

## Serialization Contract

Every public result object that inherits from `MioRomResult` provides:

```python
result.to_dict()      # JSON-ready mapping
result.to_json()      # deterministic JSON string
Result.from_dict(...) # reconstruct from mapping
Result.from_json(...) # reconstruct from JSON string
```

`from_dict()` only accepts fields declared on the dataclass. Enums, nested
result objects, tuples/sets, and dicts are normalized automatically by
`to_dict()`.

```python
from miorom.result import MioRomResult

data = table_candidate.to_dict()
json_text = table_candidate.to_json()
restored = TableCandidate.from_dict(data)
```

`TableCandidate`, `RelativeBranch`, `SwitchTable`, `FieldProfile`,
`FunctionFingerprint`, `PatchHunk`, and `XRefEntry` already follow this
contract.

## Structured Exceptions

Every exception derived from `miorom.errors.MioromError` carries
structured context:

```python
from miorom.errors import ChecksumError

try:
    verify_rom(rom)
except ChecksumError as error:
    print(error.offset, error.expected, error.actual, error.context)
```

`offset`, `expected`, `actual`, and `context` are real attributes. The
`str(error)` message stays human-readable, but don't parse the log string
for this data — read the attributes instead.

## Streaming Scanner API

Key scanners provide a generator variant alongside the list API:

```python
from itertools import islice

first = next(StringScanner.iter_strings(rom, min_length=4))
first_tables = list(islice(PointerScanner.iter_pointer_tables(rom, targets), 10))
```

`iter_*()` supports early-break and composition with `itertools`. The
original list-based API remains available and is not being removed.

## Patch Structure

A patch is not just a binary blob. IPS/BPS files can be decoded into
`PatchHunk` objects:

```python
hunks = IpsPatcher.parse(patch_bytes)
code_changes = filter_hunks(hunks, lambda hunk: hunk.offset >= 0x8000)
merged = merge_patches(hunks_a, hunks_b)
```

`PatchHunk.to_dict()` stores the payload as hex.

## Pipeline Extension

Custom pipeline steps are registered through a public API:

```python
class ValidateAssetStep(PipelineStep):
    step_type = "validate_asset"
    ...

recipe.register_step_type("validate_asset", ValidateAssetStep)
recipe.add_step(ValidateAssetStep(...))
```

Use `PipelineHook` for `before_step(step, context)` and
`after_step(step, context, success)` without forking the built-in steps.

## Path Safety Contract

Every built-in MioROM extraction function that writes a file using a name
derived from archive/ROM data (rather than a name you chose yourself)
**always** routes it through `sanitize_extract_path()` before touching the
filesystem — this prevents path traversal/zip-slip from untrusted
archives:

```python
from miorom.security import sanitize_extract_path, UnsafeArchivePathError

safe_path = sanitize_extract_path(output_dir, entry.name)
# raises UnsafeArchivePathError if entry.name tries to escape output_dir
```

This contract applies to `ArchiveContainer.extract_to_dir()`,
`DissectedArchive.extract_to_dir()`, `U8Archive.extract_all()`, and
`NARCArchive.extract_all()`. If you write your own
`BaseRomHandler.unpack()` and the filenames come from parsed data, the
same pattern is required — see the [Security Guide](SECURITY.md) for the
full checklist and known limitations (e.g. how absolute paths are
handled).

## Structural Interfaces

ABCs remain available, but external classes are not required to inherit
from MioROM. A structural-typing path is available at:

- `miorom.rom.protocols.RomHandlerProtocol`
- `miorom.project.protocols.AssetProtocol`
- `miorom.debug.protocols.EmulatorClientProtocol`

Example:

```python
from miorom.rom.manager import RomManager
from miorom.rom.protocols import RomHandlerProtocol

class ExistingRomHandler:
    name = "legacy"
    ...

if isinstance(ExistingRomHandler(), RomHandlerProtocol):
    RomManager().register(ExistingRomHandler())
```
