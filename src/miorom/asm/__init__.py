from miorom.asm.branch import ARMBranch, ThumbBranch, PowerPCBranch, MIPSBranch
from miorom.asm.branch_calc import (
    calc_arm_branch,
    resolve_arm_branch,
    calc_thumb_branch,
    resolve_thumb_branch,
    calc_mips_jump,
    resolve_mips_jump,
    calc_mips_branch,
    resolve_mips_branch,
    calc_6502_branch,
    resolve_6502_branch,
)
from miorom.asm.codecave import CodeCave, CodeCaveFinder
from miorom.asm.trampoline import TrampolineHook, HookRecord
from miorom.asm.instruction_scanner import (
    CodePointer,
    PPCInstructionScanner,
    MIPSInstructionScanner,
    ARMLiteralPointer,
    ARMMovPairPointer,
    ARMInstructionScanner,
    UniversalInstructionScanner,
)
from miorom.asm.cheat import (
    CheatCodeGenerator,
    CheatEntry,
    GeckoCode,
    ActionReplayCode,
    CWCheatCode,
    GameSharkCode,
)

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.disambiguator import (
    CodeDataDisambiguator,
    ByteClassification,
    ClassifiedRange,
    DisambiguationReport,
)
from miorom.asm.slicer import DataFlowSlicer, JumpTable
from miorom.asm.jump_table import JumpTableDetector, JumpTableResolver
from miorom.asm.ap_bypass import (
    AntiPiracyBypasser,
    APVectorType,
    APMatch,
    APBypassReport,
)
from miorom.asm.xref import (
    GlobalXrefEngine,
    XRef,
    XRefType,
    CallerGraph,
)
from miorom.asm.xref_engine import (
    SymbolicXrefEngine,
    XRefDatabase,
    XRefRecord,
    XRefDirection,
)
from miorom.asm.reloc_calc import BranchRelocator, BranchRelocation
from miorom.asm.literal_relocator import (
    CodeLiteralRelocator,
    LiteralRelocationReport,
)
from miorom.asm.micro_patcher import (
    SplitImmediateCalculator,
    StackAllocPatcher,
    OpcodeTransmuter,
)
from miorom.asm.snippet import (
    AsmSnippet,
    ArmSnippet,
    ThumbSnippet,
    MipsSnippet,
    PpcSnippet,
    SM83Snippet,
    SnesSnippet,
    M68kSnippet,
    Mos6502Snippet,
)
from miorom.asm.prologue_scanner import FunctionPrologueScanner, DiscoveredFunction
from miorom.asm.hook_manager import (
    CodeCave as HookCodeCave,
    HookRecord as HookManagerRecord,
    CodeCaveManager,
    ArmHookBuilder,
    HookManager,
)
from miorom.asm.m68k import M68kInstruction, M68kDisassembler
from miorom.asm.vwf_hook_engine import (
    VWFHookEngine,
    VWFHookConfig,
    VWFDeploymentReport,
)

__all__ = [
    "ARMBranch",
    "ThumbBranch",
    "PowerPCBranch",
    "MIPSBranch",
    "CodeCave",
    "CodeCaveFinder",
    "TrampolineHook",
    "HookRecord",
    "CodePointer",
    "PPCInstructionScanner",
    "MIPSInstructionScanner",
    "ARMLiteralPointer",
    "ARMMovPairPointer",
    "ARMInstructionScanner",
    "UniversalInstructionScanner",
    "CheatCodeGenerator",
    "CheatEntry",
    "GeckoCode",
    "ActionReplayCode",
    "CWCheatCode",
    "GameSharkCode",
    "UniversalDisassembler",
    "DisasmInstruction",
    "CodeDataDisambiguator",
    "ByteClassification",
    "ClassifiedRange",
    "DisambiguationReport",
    "DataFlowSlicer",
    "JumpTable",
    "JumpTableDetector",
    "JumpTableResolver",
    "AntiPiracyBypasser",
    "APVectorType",
    "APMatch",
    "APBypassReport",
    "GlobalXrefEngine",
    "SymbolicXrefEngine",
    "XRefDatabase",
    "XRefRecord",
    "XRefDirection",
    "XRef",
    "XRefType",
    "CallerGraph",
    "CodeLiteralRelocator",
    "LiteralRelocationReport",
    "SplitImmediateCalculator",
    "StackAllocPatcher",
    "OpcodeTransmuter",
    "AsmSnippet",
    "ArmSnippet",
    "ThumbSnippet",
    "MipsSnippet",
    "PpcSnippet",
    "SM83Snippet",
    "SnesSnippet",
    "M68kSnippet",
    "Mos6502Snippet",
    "FunctionPrologueScanner",
    "DiscoveredFunction",
    "HookCodeCave",
    "HookManagerRecord",
    "CodeCaveManager",
    "ArmHookBuilder",
    "HookManager",
    "M68kInstruction",
    "M68kDisassembler",
    "calc_arm_branch",
    "resolve_arm_branch",
    "calc_thumb_branch",
    "resolve_thumb_branch",
    "calc_mips_jump",
    "resolve_mips_jump",
    "calc_mips_branch",
    "resolve_mips_branch",
    "calc_6502_branch",
    "resolve_6502_branch",
    "BranchRelocator",
    "BranchRelocation",
    "VWFHookEngine",
    "VWFHookConfig",
    "VWFDeploymentReport",
]
