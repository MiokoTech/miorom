import pytest

from miorom.core.scanner import PointerScanner, StringScanner
from miorom.core.struct_profiler import FieldType, FieldProfile
from miorom.debug.protocols import EmulatorClientProtocol
from miorom.diff.bindiff import FunctionFingerprint
from miorom.errors import ChecksumError, MioromError
from miorom.patch import BpsPatcher, IpsPatcher, PatchHunk, filter_hunks, merge_patches
from miorom.pipeline import PipelineHook, PipelineRecipe, PipelineStep
from miorom.project.protocols import AssetProtocol
from miorom.result import MioRomResult
from miorom.rom.protocols import RomHandlerProtocol
from miorom.rom.manager import RomManager
from miorom.scanner.table_detector import HeuristicTableDetector
from miorom.script.branch import BytecodeBranchScanner, RelativeBranch
from miorom.scanner.xref import XRefEntry, XRefType


def test_public_result_serialization_contract():
    branch = RelativeBranch(pc=16, opcode=0x20, offset=8, target=32, offset_pos=17)
    restored = RelativeBranch.from_json(branch.to_json())
    assert restored == branch

    field = FieldProfile(0, 4, FieldType.UINT32_LE, "count", constant_value=7)
    assert field.to_dict()["field_type"] == "uint32_le"
    assert FieldProfile.from_dict(field.to_dict()) == field

    xref = XRefEntry(8, 24, XRefType.CODE_CALL, "test")
    assert XRefEntry.from_dict(xref.to_dict()) == xref


def test_length_offset_table_generator_wraps_list_api():
    candidates = HeuristicTableDetector.iter_length_offset_tables(
        b"\x08\x00\x00\x00abcdef", candidate_strides=(6,), min_records=1
    )
    assert all(candidate.stride == 6 for candidate in candidates)


def test_structural_protocol_types_are_runtime_compatible():
    class StructuralHandler:
        name = "structural"
        def can_handle(self, data, filepath=None): return False
        def unpack(self, data, output_dir, **kwargs): return {}
        def repack(self, input_dir, **kwargs): return b""

    class StructuralEmulator:
        def read_bytes(self, address, size): return bytes(size)
        def write_bytes(self, address, data): return None

    assert isinstance(StructuralHandler(), RomHandlerProtocol)
    assert isinstance(StructuralEmulator(), EmulatorClientProtocol)
    manager = RomManager()
    manager.register(StructuralHandler())
    assert manager.get_handler("structural").name == "structural"

    assert isinstance(FunctionFingerprint(0, "sub", 1, 0, 1, 1), MioRomResult)


def test_structured_exception_context_is_machine_readable():
    error = ChecksumError(
        "Header checksum mismatch",
        offset=12,
        expected=0x1234,
        actual=0x5678,
        context={"algorithm": "gb_header"},
    )
    assert isinstance(error, MioromError)
    assert error.offset == 12
    assert (error.expected, error.actual) == (0x1234, 0x5678)
    assert error.context["algorithm"] == "gb_header"
    assert str(error) == "Header checksum mismatch"
    assert "offset=0xC" in repr(error)


def test_patch_hunk_parse_filter_merge_and_roundtrip():
    source = b"AAAABBBBCCCC"
    modified = bytearray(source)
    modified[0:2] = b"XY"
    modified[6] = ord("Z")
    patch = IpsPatcher.create(source, modified)
    hunks = IpsPatcher.parse(patch)
    assert sum(len(hunk.data) for hunk in hunks) == 3
    assert PatchHunk.from_dict(hunks[0].to_dict()) == hunks[0]

    selected = filter_hunks(hunks, lambda hunk: hunk.offset >= 4)
    assert all(hunk.offset >= 4 for hunk in selected)
    merged = merge_patches(hunks, selected)
    assert merged

    bps = BpsPatcher.create(source, bytes(modified))
    assert BpsPatcher.parse(bps, source) == hunks


def test_scanner_iterators_support_early_exit():
    data = b"first\0second\0third\0"
    iterator = StringScanner.iter_strings(data, min_length=3)
    assert next(iterator).text == "first"

    targets = [5, 12]
    pointer_data = bytes.fromhex("05000000 00000000 0C000000 00000000".replace(" ", ""))
    tables = PointerScanner.iter_pointer_tables(pointer_data, targets, strides=(4,), base_offsets=[0])
    assert all(table.stride == 4 for table in tables)

    branch = next(BytecodeBranchScanner.iter_relative_branches(
        bytes.fromhex("20010000AAAAAAAA"), {0x20}, base_pc_delta=3
    ))
    assert branch.opcode == 0x20

    table_data = bytes.fromhex("18000000 41414141 00 20000000 42424242 00")
    candidates = HeuristicTableDetector.iter_stride_records(table_data, candidate_strides=(6,), min_records=2)
    assert all(candidate.stride == 6 for candidate in candidates)


def test_pipeline_registry_and_hooks_are_public():
    events = []

    class AppendStep(PipelineStep):
        step_type = "append_contract"

        def __init__(self, value):
            self.value = value

        def run(self, context):
            context.set("values", context.get("values", []) + [self.value])
            return True

        def to_dict(self):
            return {"step_type": self.step_type, "value": self.value}

        @classmethod
        def from_dict(cls, data):
            return cls(data["value"])

    class Hook(PipelineHook):
        def before_step(self, step, context):
            events.append(("before", step.step_type))

        def after_step(self, step, context, success):
            events.append(("after", step.step_type, success))

    recipe = PipelineRecipe()
    recipe.register_step_type("append_contract", AppendStep)
    recipe.add_step(AppendStep("one"))
    recipe.add_hook(Hook())
    recipe.add_step(AppendStep("two"))
    context = recipe.execute()
    assert context.get("values") == ["one", "two"]
    assert events == [
        ("before", "append_contract"),
        ("after", "append_contract", True),
        ("before", "append_contract"),
        ("after", "append_contract", True),
    ]

    loaded = PipelineRecipe.from_dict(recipe.to_dict())
    assert [step.value for step in loaded.steps] == ["one", "two"]


def test_structural_handlers_pass_runtime_protocols():
    class ExternalRomHandler:
        name = "external"

        def can_handle(self, data, filepath=None):
            return data.startswith(b"EXT")

        def unpack(self, data, output_dir, **kwargs):
            return {"format": self.name}

        def repack(self, input_dir, **kwargs):
            return b"EXT"

    class ExternalEmulator:
        def read_bytes(self, address, size):
            return b"\0" * size

        def write_bytes(self, address, data):
            return None

    class ExternalAsset:
        id = "external_asset"
        source = "memory"

        def extract_text(self, context=None):
            return []

        def repack_text(self, rows, context=None):
            return b""

    assert isinstance(ExternalRomHandler(), RomHandlerProtocol)
    assert isinstance(ExternalEmulator(), EmulatorClientProtocol)
    assert isinstance(ExternalAsset(), AssetProtocol)

    manager = RomManager()
    manager.register(ExternalRomHandler())
    assert "external" in manager.handlers
