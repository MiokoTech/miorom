"""
miorom.platforms.psp.prx
~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation Portable (PSP) Relocatable Executable (PRX) parser,
MIPS module inspector, NID (Name Identifier) resolver, and stub hooker.

PRX files are 32-bit Little-Endian MIPS ELF executables (BOOT.BIN, EBOOT.BIN,
and .prx dynamic modules) containing Sony module metadata (sceModuleInfo),
export library tables, and import stub tables keyed by 32-bit NID hashes.
"""

import hashlib
import io
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.core.schema import (
    U8,
    U16,
    U32,
    BinaryStruct,
    RawBytes,
    unpack_from,
)
from miorom.errors import ParseError
from miorom.result import MioRomResult

ELF_MAGIC = b"\x7fELF"
PSP_ENCRYPTED_MAGIC = b"~PSP"

# ELF Machine and Type Constants
EM_MIPS = 8

ET_EXEC = 2
ET_SCE_EXEC = 0xFFA0
ET_SCE_RELEXEC = 0xFFA4

# Section Types
SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8
SHT_REL = 9
SHT_PRXREL = 0x700000A0

# Standard PSP SDK Function Names for Dynamic NID Database
PSP_SDK_KNOWN_FUNCTIONS = [
    # sceDisplay
    "sceDisplayWaitVblankStart",
    "sceDisplayWaitVblankStartCB",
    "sceDisplayWaitVblank",
    "sceDisplayWaitVblankCB",
    "sceDisplaySetMode",
    "sceDisplayGetMode",
    "sceDisplaySetFrameBuf",
    "sceDisplayGetFrameBuf",
    "sceDisplayIsVblank",
    "sceDisplayGetVcount",
    "sceDisplayGetCurrentHcount",
    "sceDisplayGetAccumulatedHcount",
    "sceDisplayAdjustFrameBuf",
    # sceCtrl
    "sceCtrlReadBufferPositive",
    "sceCtrlPeekBufferPositive",
    "sceCtrlReadBufferNegative",
    "sceCtrlPeekBufferNegative",
    "sceCtrlSetSamplingCycle",
    "sceCtrlGetSamplingCycle",
    "sceCtrlSetSamplingMode",
    "sceCtrlGetSamplingMode",
    "sceCtrlReadLatch",
    # sceIo
    "sceIoOpen",
    "sceIoClose",
    "sceIoRead",
    "sceIoWrite",
    "sceIoLseek",
    "sceIoLseek32",
    "sceIoRemove",
    "sceIoMkdir",
    "sceIoRmdir",
    "sceIoChdir",
    "sceIoSync",
    "sceIoGetstat",
    "sceIoChstat",
    "sceIoRename",
    "sceIoDopen",
    "sceIoDread",
    "sceIoDclose",
    "sceIoDevctl",
    "sceIoAssign",
    "sceIoUnassign",
    # sceAudio
    "sceAudioOutput",
    "sceAudioOutputBlocking",
    "sceAudioOutputPanned",
    "sceAudioOutputPannedBlocking",
    "sceAudioChReserve",
    "sceAudioChRelease",
    "sceAudioSetChannelDataLen",
    "sceAudioChangeChannelConfig",
    "sceAudioChangeChannelVolume",
    "sceAudioSRCChReserve",
    "sceAudioSRCChRelease",
    "sceAudioSRCOutputBlocking",
    # sceKernel
    "sceKernelExitGame",
    "sceKernelCreateThread",
    "sceKernelDeleteThread",
    "sceKernelStartThread",
    "sceKernelExitThread",
    "sceKernelExitDeleteThread",
    "sceKernelTerminateThread",
    "sceKernelTerminateDeleteThread",
    "sceKernelSuspendThread",
    "sceKernelResumeThread",
    "sceKernelWakeupThread",
    "sceKernelCancelWakeupThread",
    "sceKernelSleepThread",
    "sceKernelSleepThreadCB",
    "sceKernelDelayThread",
    "sceKernelDelayThreadCB",
    "sceKernelDelaySysClockThread",
    "sceKernelDelaySysClockThreadCB",
    "sceKernelGetThreadId",
    "sceKernelGetThreadCurrentPriority",
    "sceKernelChangeThreadPriority",
    "sceKernelCreateSema",
    "sceKernelDeleteSema",
    "sceKernelSignalSema",
    "sceKernelWaitSema",
    "sceKernelWaitSemaCB",
    "sceKernelPollSema",
    "sceKernelCreateEventFlag",
    "sceKernelDeleteEventFlag",
    "sceKernelSetEventFlag",
    "sceKernelClearEventFlag",
    "sceKernelWaitEventFlag",
    "sceKernelWaitEventFlagCB",
    "sceKernelPollEventFlag",
    "sceKernelCreateMsgPipe",
    "sceKernelDeleteMsgPipe",
    "sceKernelSendMsgPipe",
    "sceKernelReceiveMsgPipe",
    "sceKernelCreateMbx",
    "sceKernelDeleteMbx",
    "sceKernelSendMbx",
    "sceKernelReceiveMbx",
    "sceKernelCreateFpl",
    "sceKernelDeleteFpl",
    "sceKernelAllocateFpl",
    "sceKernelFreeFpl",
    "sceKernelCreateVpl",
    "sceKernelDeleteVpl",
    "sceKernelAllocateVpl",
    "sceKernelFreeVpl",
    "sceKernelAllocPartitionMemory",
    "sceKernelFreePartitionMemory",
    "sceKernelGetBlockHeadAddr",
    "sceKernelMaxFreeMemSize",
    "sceKernelTotalFreeMemSize",
    "sceKernelRegisterExitCallback",
    "sceKernelCreateCallback",
    "sceKernelDeleteCallback",
    "sceKernelNotifyCallback",
    "sceKernelCancelCallback",
    "sceKernelGetCallbackCount",
    "sceKernelCheckCallback",
    "sceKernelLoadModule",
    "sceKernelStartModule",
    "sceKernelStopModule",
    "sceKernelUnloadModule",
    "sceKernelSearchModuleByName",
    "sceKernelGetModuleIdByAddress",
    "sceKernelDcacheWritebackAll",
    "sceKernelDcacheWritebackInvalidateAll",
    "sceKernelDcacheWritebackRange",
    "sceKernelDcacheWritebackInvalidateRange",
    "sceKernelDcacheInvalidateRange",
    "sceKernelIcacheInvalidateAll",
    "sceKernelIcacheInvalidateRange",
    "sceKernelGetSystemTime",
    "sceKernelGetSystemTimeLow",
    "sceKernelGetSystemTimeWide",
    "sceKernelLibcClock",
    "sceKernelLibcTime",
    "sceKernelLibcGettimeofday",
    "sceKernelSetCompilerVersion",
    # sceFont
    "sceFontOpen",
    "sceFontOpenUserMemory",
    "sceFontOpenUserFile",
    "sceFontClose",
    "sceFontFindOptimumFont",
    "sceFontFindFont",
    "sceFontGetFontInfo",
    "sceFontGetFontInfoByIndexNumber",
    "sceFontGetCharInfo",
    "sceFontGetGlyphImage",
    "sceFontGetGlyphImage_Clip",
    "sceFontPixelToPointH",
    "sceFontPixelToPointV",
    "sceFontPointToPixelH",
    "sceFontPointToPixelV",
    "sceFontCalcMemorySize",
    "sceFontNewLib",
    "sceFontDoneLib",
    # scePower
    "scePowerGetBatteryLifePercent",
    "scePowerGetBatteryLifeTime",
    "scePowerGetBatteryRemainCapacity",
    "scePowerGetBatteryFullCapacity",
    "scePowerGetBatteryVolt",
    "scePowerGetBatteryElec",
    "scePowerGetBatteryTemp",
    "scePowerIsBatteryExist",
    "scePowerIsBatteryCharging",
    "scePowerIsPowerOnline",
    "scePowerSetClockFrequency",
    "scePowerSetCpuClockFrequency",
    "scePowerSetBusClockFrequency",
    "scePowerGetCpuClockFrequency",
    "scePowerGetBusClockFrequency",
    "scePowerLock",
    "scePowerUnlock",
    "scePowerTick",
    # sceUtility
    "sceUtilityMsgDialogInitStart",
    "sceUtilityMsgDialogUpdate",
    "sceUtilityMsgDialogGetStatus",
    "sceUtilityMsgDialogAbort",
    "sceUtilitySavedataInitStart",
    "sceUtilitySavedataUpdate",
    "sceUtilitySavedataGetStatus",
    "sceUtilityNetconfInitStart",
    "sceUtilityNetconfUpdate",
    "sceUtilityNetconfGetStatus",
    "sceUtilityOskInitStart",
    "sceUtilityOskUpdate",
    "sceUtilityOskGetStatus",
    "sceUtilityOskShutdownStart",
    # sceRtc
    "sceRtcGetCurrentTick",
    "sceRtcGetCurrentClock",
    "sceRtcGetCurrentClockLocalTime",
    "sceRtcGetTickResolution",
    "sceRtcSetTick",
    "sceRtcGetTick",
    "sceRtcCompareTick",
    "sceRtcTickAddTicks",
    # sceGe
    "sceGeListEnQueue",
    "sceGeListEnQueueHead",
    "sceGeListDeQueue",
    "sceGeListUpdateStallAddr",
    "sceGeListSync",
    "sceGeDrawSync",
    "sceGeBreak",
    "sceGeContinue",
    "sceGeEdramGetAddr",
    "sceGeEdramGetSize",
    # sceUmd
    "sceUmdCheckMedium",
    "sceUmdActivate",
    "sceUmdDeactivate",
    "sceUmdWaitDriveStat",
    "sceUmdWaitDriveStatCB",
    "sceUmdCancelWaitDriveStat",
    "sceUmdGetDriveStat",
    "sceUmdGetErrorStat",
    "sceUmdRegisterUMDCallback",
    "sceUmdUnRegisterUMDCallback",
    # Module lifecycle
    "module_start",
    "module_stop",
    "module_info",
    "module_reboot_before",
]


class Elf32HeaderStruct(BinaryStruct):
    """ELF32 52-byte header for Little-Endian MIPS binaries."""

    e_ident_magic = RawBytes(4)  # b"\x7fELF"
    e_ident_class = U8()  # 1 = 32-bit
    e_ident_data = U8()  # 1 = Little-endian
    e_ident_version = U8()  # 1
    e_ident_osabi = U8()  # 0
    e_ident_abiversion = U8()  # 0
    e_ident_pad = RawBytes(7)  # 7-byte padding
    e_type = U16()  # 0x0002 / 0xFFA0 / 0xFFA4
    e_machine = U16()  # 0x0008 (MIPS)
    e_version = U32()  # 1
    e_entry = U32()  # Entry point address
    e_phoff = U32()  # Program header offset
    e_shoff = U32()  # Section header offset
    e_flags = U32()  # MIPS ABI flags
    e_ehsize = U16()  # ELF header size (52)
    e_phentsize = U16()  # Program header entry size
    e_phnum = U16()  # Program header count
    e_shentsize = U16()  # Section header entry size (40)
    e_shnum = U16()  # Section header count
    e_shstrndx = U16()  # Section string table index


class Elf32SectionHeaderStruct(BinaryStruct):
    """ELF32 40-byte section header."""

    sh_name = U32()  # String table offset
    sh_type = U32()  # SHT_PROGBITS, SHT_STRTAB, etc.
    sh_flags = U32()  # Flags (SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR)
    sh_addr = U32()  # Virtual address in memory
    sh_offset = U32()  # File offset in PRX
    sh_size = U32()  # Section size in bytes
    sh_link = U32()  # Associated section link
    sh_info = U32()  # Extra section info
    sh_addralign = U32()  # Address alignment
    sh_entsize = U32()  # Entry size if section holds a table


class SceModuleInfoStruct(BinaryStruct):
    """Sony sceModuleInfo 52-byte descriptor structure."""

    modattribute = U16()  # 0x0000 = User mode, 0x1000 = Kernel mode
    modversion_minor = U8()  # Minor module version
    modversion_major = U8()  # Major module version
    modname = RawBytes(28)  # ASCII null-terminated name
    gp_value = U32()  # Global pointer ($gp) initial value
    ent_top = U32()  # Export table start virtual address
    ent_end = U32()  # Export table end virtual address
    stub_top = U32()  # Import table start virtual address
    stub_end = U32()  # Import table end virtual address


class SceLibraryEntryStruct(BinaryStruct):
    """Sony SceLibraryEntry (export library descriptor)."""

    name_addr = U32()  # VA of library name string (0 for noname/syslib)
    version = U16()  # Library version
    attribute = U16()  # 0x8000 = syslib, 0 = normal
    ent_len = U8()  # Struct length in 32-bit words (usually 4 = 16 bytes)
    var_count = U8()  # Number of exported variables
    func_count = U16()  # Number of exported functions
    entry_table = U32()  # VA of entry table (NIDs followed by pointers)


class SceLibraryStubStruct(BinaryStruct):
    """Sony SceLibraryStub (import library stub descriptor)."""

    name_addr = U32()  # VA of library name string
    version = U16()  # Library version
    flags = U16()  # Flags / attributes
    stub_len = U8()  # Struct length in 32-bit words (usually 5 = 20 bytes)
    var_count = U8()  # Number of imported variables
    func_count = U16()  # Number of imported functions
    nid_table = U32()  # VA of NID table
    stub_table = U32()  # VA of MIPS stub code table


class PSPNIDResolver:
    """
    Bidirectional Sony PSP Name Identifier (NID) resolver.
    Calculates 32-bit NIDs dynamically using SHA-1 and resolves standard Sony SDK symbols.
    """

    _nid_to_name: Dict[int, str] = {}
    _name_to_nid: Dict[str, int] = {}
    _initialized: bool = False

    @classmethod
    def _init_db(cls):
        if cls._initialized:
            return
        for func_name in PSP_SDK_KNOWN_FUNCTIONS:
            nid = cls.calculate_nid(func_name)
            cls._nid_to_name[nid] = func_name
            cls._name_to_nid[func_name] = nid
        cls._initialized = True

    @classmethod
    def calculate_nid(cls, name: str) -> int:
        """Calculate the 32-bit unsigned little-endian NID for a symbol name using SHA-1."""
        h = hashlib.sha1(name.encode("ascii")).digest()[:4]
        return unpack_from("<I", h, 0)[0]

    @classmethod
    def resolve_nid(cls, nid: int) -> Optional[str]:
        """Resolve a 32-bit NID to its official Sony function name, or None if unknown."""
        cls._init_db()
        return cls._nid_to_name.get(nid)

    @classmethod
    def resolve_name(cls, name: str) -> int:
        """Resolve a function name to its 32-bit NID."""
        cls._init_db()
        if name in cls._name_to_nid:
            return cls._name_to_nid[name]
        nid = cls.calculate_nid(name)
        cls.register_nid(nid, name)
        return nid

    @classmethod
    def register_nid(cls, nid: int, name: str):
        """Register a custom or game-specific NID mapping."""
        cls._init_db()
        cls._nid_to_name[nid] = name
        cls._name_to_nid[name] = nid


@dataclass
class PRXModuleInfo(MioRomResult):
    """High-level module metadata parsed from SceModuleInfo."""

    name: str
    major_version: int
    minor_version: int
    is_kernel_mode: bool
    gp_value: int
    entry_point: int
    ent_top: int
    ent_end: int
    stub_top: int
    stub_end: int


@dataclass
class PRXImportFunction(MioRomResult):
    """An imported function stub inside a PRX library stub entry."""

    nid: int
    name: Optional[str] = None
    nid_offset: int = 0
    stub_offset: int = 0
    stub_addr: int = 0


@dataclass
class PRXImportVariable(MioRomResult):
    """An imported variable stub inside a PRX library stub entry."""

    nid: int
    name: Optional[str] = None
    nid_offset: int = 0
    stub_offset: int = 0
    stub_addr: int = 0


@dataclass
class PRXImportLibrary(MioRomResult):
    """An imported Sony PSP library (e.g. sceDisplay_driver, sceIo_driver)."""

    name: str
    version: int
    flags: int
    functions: List[PRXImportFunction] = field(default_factory=list)
    variables: List[PRXImportVariable] = field(default_factory=list)


@dataclass
class PRXExportFunction(MioRomResult):
    """An exported function in a PRX module."""

    nid: int
    name: Optional[str] = None
    entry_point: int = 0


@dataclass
class PRXExportVariable(MioRomResult):
    """An exported variable in a PRX module."""

    nid: int
    name: Optional[str] = None
    address: int = 0


@dataclass
class PRXExportLibrary(MioRomResult):
    """An exported library provided by the PRX module (e.g. syslib)."""

    name: str
    version: int
    attribute: int
    functions: List[PRXExportFunction] = field(default_factory=list)
    variables: List[PRXExportVariable] = field(default_factory=list)


@dataclass
class PRXSection(MioRomResult):
    """ELF section metadata and byte range."""

    name: str
    sh_type: int
    sh_flags: int
    sh_addr: int
    sh_offset: int
    sh_size: int
    sh_link: int
    sh_info: int
    sh_addralign: int
    sh_entsize: int


class PRXModule:
    """
    Sony PlayStation Portable (PSP) Relocatable Executable (PRX) module.
    Supports inspecting module info, resolving NIDs, enumerating imports/exports,
    patching MIPS call stubs, and serializing byte-exact binaries.
    """

    def __init__(self, raw_data: bytes):
        if len(raw_data) >= 4 and raw_data[:4] == PSP_ENCRYPTED_MAGIC:
            raise ParseError(
                "Encrypted PSP executable detected (~PSP header). "
                "Official PSP UMD discs provide the exact unencrypted plain ELF/PRX at "
                "'PSP_GAME/SYSDIR/BOOT.BIN'. Please inspect BOOT.BIN instead."
            )

        if len(raw_data) < 52 or raw_data[:4] != ELF_MAGIC:
            raise ParseError(
                f"Invalid PSP PRX: expected ELF magic '\\x7fELF', got {raw_data[:4]!r}"
            )

        self.raw_data = bytearray(raw_data)
        self.header = Elf32HeaderStruct.from_bytes(self.raw_data, offset=0, endian="<")

        if self.header.e_ident_class != 1:
            raise ParseError("Only 32-bit ELF binaries (ELF32) are supported.")
        if self.header.e_ident_data != 1:
            raise ParseError("Only Little-Endian MIPS binaries are supported.")
        if self.header.e_machine != EM_MIPS:
            raise ParseError(
                f"Invalid architecture: expected MIPS (EM_MIPS=8), got {self.header.e_machine}"
            )

        self.sections: List[PRXSection] = []
        self.section_map: Dict[str, PRXSection] = {}
        self.module_info: Optional[PRXModuleInfo] = None
        self.imports: List[PRXImportLibrary] = []
        self.exports: List[PRXExportLibrary] = []

        self._parse_sections()
        self._parse_module_info()
        self._parse_exports()
        self._parse_imports()

    @classmethod
    def from_bytes(cls, data: bytes) -> "PRXModule":
        """Parse a PRX module from raw bytes."""
        return cls(data)

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike]) -> "PRXModule":
        """Read and parse a PRX module from a filesystem path."""
        with open(path, "rb") as f:
            return cls(f.read())

    def to_bytes(self) -> bytes:
        """Serialize the PRX module back to bytes."""
        return bytes(self.raw_data)

    def save(self, path: Union[str, os.PathLike]):
        """Save the PRX module to a file."""
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def _get_string(self, offset: int) -> str:
        """Read a null-terminated ASCII string from a raw buffer offset."""
        if offset >= len(self.raw_data):
            return ""
        end = self.raw_data.find(b"\x00", offset)
        if end == -1:
            end = len(self.raw_data)
        return self.raw_data[offset:end].decode("ascii", errors="replace")

    def _parse_sections(self):
        """Parse section header table and section names."""
        shoff = self.header.e_shoff
        shentsize = self.header.e_shentsize
        shnum = self.header.e_shnum

        raw_sections = []
        for i in range(shnum):
            sec_hdr = Elf32SectionHeaderStruct.from_bytes(
                self.raw_data, offset=shoff + i * shentsize, endian="<"
            )
            raw_sections.append(sec_hdr)

        shstrtab_offset = 0
        if 0 <= self.header.e_shstrndx < len(raw_sections):
            shstrtab_offset = raw_sections[self.header.e_shstrndx].sh_offset

        for hdr in raw_sections:
            name = ""
            if shstrtab_offset > 0:
                name = self._get_string(shstrtab_offset + hdr.sh_name)

            sec = PRXSection(
                name=name,
                sh_type=hdr.sh_type,
                sh_flags=hdr.sh_flags,
                sh_addr=hdr.sh_addr,
                sh_offset=hdr.sh_offset,
                sh_size=hdr.sh_size,
                sh_link=hdr.sh_link,
                sh_info=hdr.sh_info,
                sh_addralign=hdr.sh_addralign,
                sh_entsize=hdr.sh_entsize,
            )
            self.sections.append(sec)
            if name:
                self.section_map[name] = sec

    def va_to_offset(self, va: int) -> int:
        """
        Translate a virtual memory address to its corresponding file offset in the PRX buffer.
        Handles both section-mapped addresses and zero-base relocatable modules.
        """
        for sec in self.sections:
            if sec.sh_type != SHT_NOBITS and sec.sh_size > 0:
                if sec.sh_addr <= va < sec.sh_addr + sec.sh_size:
                    return sec.sh_offset + (va - sec.sh_addr)

        # Fallback for relocatable PRX where base VA directly indexes file offsets
        if 0 <= va < len(self.raw_data):
            return va

        raise ParseError(
            f"Cannot resolve virtual address 0x{va:08X} to PRX file offset"
        )

    def _parse_module_info(self):
        """Locate and parse the SceModuleInfo structure."""
        modinfo_sec = self.section_map.get(".rodata.sceModuleInfo")
        offset: Optional[int] = None

        if modinfo_sec and modinfo_sec.sh_size >= 52:
            offset = modinfo_sec.sh_offset
        else:
            # Look for any section ending with sceModuleInfo
            for name, sec in self.section_map.items():
                if "sceModuleInfo" in name and sec.sh_size >= 52:
                    offset = sec.sh_offset
                    break

        if offset is None:
            # If not in named sections, look for common offset or check program headers
            return

        info_struct = SceModuleInfoStruct.from_bytes(
            self.raw_data, offset=offset, endian="<"
        )
        mod_name = (
            info_struct.modname.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        )

        self.module_info = PRXModuleInfo(
            name=mod_name,
            major_version=info_struct.modversion_major,
            minor_version=info_struct.modversion_minor,
            is_kernel_mode=bool(info_struct.modattribute & 0x1000),
            gp_value=info_struct.gp_value,
            entry_point=self.header.e_entry,
            ent_top=info_struct.ent_top,
            ent_end=info_struct.ent_end,
            stub_top=info_struct.stub_top,
            stub_end=info_struct.stub_end,
        )

    def _parse_exports(self):
        """Parse exported library entries from ent_top to ent_end."""
        if not self.module_info or self.module_info.ent_top == 0:
            return

        try:
            cur_offset = self.va_to_offset(self.module_info.ent_top)
            end_offset = self.va_to_offset(self.module_info.ent_end)
        except ParseError:
            return

        while cur_offset + 16 <= end_offset and cur_offset + 16 <= len(self.raw_data):
            entry_struct = SceLibraryEntryStruct.from_bytes(
                self.raw_data, offset=cur_offset, endian="<"
            )

            # Resolve library name
            lib_name = "syslib"
            if entry_struct.name_addr != 0:
                try:
                    name_off = self.va_to_offset(entry_struct.name_addr)
                    lib_name = self._get_string(name_off)
                except ParseError:
                    pass

            exp_lib = PRXExportLibrary(
                name=lib_name,
                version=entry_struct.version,
                attribute=entry_struct.attribute,
            )

            if entry_struct.entry_table != 0:
                try:
                    tbl_off = self.va_to_offset(entry_struct.entry_table)
                    func_count = entry_struct.func_count
                    var_count = entry_struct.var_count

                    # NID table followed by pointer table
                    # func_count function NIDs
                    func_nids = []
                    for i in range(func_count):
                        fn_nid = unpack_from("<I", self.raw_data, tbl_off + i * 4)[0]
                        func_nids.append(fn_nid)

                    # var_count variable NIDs
                    var_nids = []
                    var_nid_start = tbl_off + func_count * 4
                    for i in range(var_count):
                        vn_nid = unpack_from("<I", self.raw_data, var_nid_start + i * 4)[0]
                        var_nids.append(vn_nid)

                    # Pointer table
                    ptr_start = tbl_off + (func_count + var_count) * 4
                    for i, fn_nid in enumerate(func_nids):
                        fn_ptr = unpack_from("<I", self.raw_data, ptr_start + i * 4)[0]
                        resolved = PSPNIDResolver.resolve_nid(fn_nid)
                        exp_lib.functions.append(
                            PRXExportFunction(
                                nid=fn_nid,
                                name=resolved,
                                entry_point=fn_ptr,
                            )
                        )

                    var_ptr_start = ptr_start + func_count * 4
                    for i, vn_nid in enumerate(var_nids):
                        vn_ptr = unpack_from("<I", self.raw_data, var_ptr_start + i * 4)[0]
                        resolved = PSPNIDResolver.resolve_nid(vn_nid)
                        exp_lib.variables.append(
                            PRXExportVariable(
                                nid=vn_nid,
                                name=resolved,
                                address=vn_ptr,
                            )
                        )
                except ParseError:
                    pass

            self.exports.append(exp_lib)
            step = max(entry_struct.ent_len * 4, 16)
            cur_offset += step

    def _parse_imports(self):
        """Parse imported library stub entries from stub_top to stub_end."""
        if not self.module_info or self.module_info.stub_top == 0:
            return

        try:
            cur_offset = self.va_to_offset(self.module_info.stub_top)
            end_offset = self.va_to_offset(self.module_info.stub_end)
        except ParseError:
            return

        while cur_offset + 20 <= end_offset and cur_offset + 20 <= len(self.raw_data):
            stub_struct = SceLibraryStubStruct.from_bytes(
                self.raw_data, offset=cur_offset, endian="<"
            )

            lib_name = "unknown_driver"
            if stub_struct.name_addr != 0:
                try:
                    name_off = self.va_to_offset(stub_struct.name_addr)
                    lib_name = self._get_string(name_off)
                except ParseError:
                    pass

            imp_lib = PRXImportLibrary(
                name=lib_name,
                version=stub_struct.version,
                flags=stub_struct.flags,
            )

            if stub_struct.nid_table != 0:
                try:
                    nid_off = self.va_to_offset(stub_struct.nid_table)
                    stub_off = (
                        self.va_to_offset(stub_struct.stub_table)
                        if stub_struct.stub_table != 0
                        else 0
                    )

                    for i in range(stub_struct.func_count):
                        fn_nid_off = nid_off + i * 4
                        fn_nid = unpack_from("<I", self.raw_data, fn_nid_off)[0]
                        resolved = PSPNIDResolver.resolve_nid(fn_nid)
                        call_stub_off = stub_off + i * 8 if stub_off > 0 else 0
                        call_stub_addr = (
                            stub_struct.stub_table + i * 8
                            if stub_struct.stub_table != 0
                            else 0
                        )

                        imp_lib.functions.append(
                            PRXImportFunction(
                                nid=fn_nid,
                                name=resolved,
                                nid_offset=fn_nid_off,
                                stub_offset=call_stub_off,
                                stub_addr=call_stub_addr,
                            )
                        )

                    if stub_struct.var_count > 0:
                        var_nid_start = nid_off + stub_struct.func_count * 4
                        vstub_table_va = 0
                        vstub_off = 0
                        # 6th word in SceLibraryStub (offset 20 from cur_offset) if stub_len >= 6
                        if stub_struct.stub_len >= 6 and cur_offset + 24 <= len(self.raw_data):
                            vstub_table_va = unpack_from("<I", self.raw_data, cur_offset + 20)[0]
                            if vstub_table_va != 0:
                                try:
                                    vstub_off = self.va_to_offset(vstub_table_va)
                                except ParseError:
                                    vstub_off = 0

                        for i in range(stub_struct.var_count):
                            vn_nid_off = var_nid_start + i * 4
                            vn_nid = unpack_from("<I", self.raw_data, vn_nid_off)[0]
                            resolved = PSPNIDResolver.resolve_nid(vn_nid)
                            call_vstub_off = vstub_off + i * 8 if vstub_off > 0 else 0
                            call_vstub_addr = vstub_table_va + i * 8 if vstub_table_va != 0 else 0

                            imp_lib.variables.append(
                                PRXImportVariable(
                                    nid=vn_nid,
                                    name=resolved,
                                    nid_offset=vn_nid_off,
                                    stub_offset=call_vstub_off,
                                    stub_addr=call_vstub_addr,
                                )
                            )
                except ParseError:
                    pass

            self.imports.append(imp_lib)
            step = max(stub_struct.stub_len * 4, 20)
            cur_offset += step

    def list_imports(self) -> List[PRXImportLibrary]:
        """Return list of imported libraries and their functions."""
        return list(self.imports)

    def list_exports(self) -> List[PRXExportLibrary]:
        """Return list of exported libraries and their functions."""
        return list(self.exports)

    def find_import(
        self, lib_name: str, nid_or_name: Union[int, str]
    ) -> Optional[PRXImportFunction]:
        """Find an imported function by library name and NID or function name."""
        for lib in self.imports:
            if lib.name.lower() == lib_name.lower():
                for fn in lib.functions:
                    if isinstance(nid_or_name, int) and fn.nid == nid_or_name:
                        return fn
                    if isinstance(nid_or_name, str):
                        if fn.name and fn.name.lower() == nid_or_name.lower():
                            return fn
                        # Also check if nid matches calculated
                        if fn.nid == PSPNIDResolver.calculate_nid(nid_or_name):
                            if fn.name is None:
                                fn.name = nid_or_name
                                PSPNIDResolver.register_nid(fn.nid, nid_or_name)
                            return fn
        return None

    def find_import_variable(
        self, lib_name: str, nid_or_name: Union[int, str]
    ) -> Optional[PRXImportVariable]:
        """Find an imported variable by library name and NID or variable name."""
        for lib in self.imports:
            if lib.name.lower() == lib_name.lower():
                for v in lib.variables:
                    if isinstance(nid_or_name, int) and v.nid == nid_or_name:
                        return v
                    if isinstance(nid_or_name, str):
                        if v.name and v.name.lower() == nid_or_name.lower():
                            return v
                        if v.nid == PSPNIDResolver.calculate_nid(nid_or_name):
                            if v.name is None:
                                v.name = nid_or_name
                                PSPNIDResolver.register_nid(v.nid, nid_or_name)
                            return v
        return None

    def redirect_stub(
        self,
        lib_name: str,
        nid_or_name: Union[int, str],
        target_addr: int,
    ):
        """
        Redirect an imported MIPS function call stub to jump directly to target_addr.
        Encodes a MIPS 'j target_addr' opcode and 'nop' delay slot:
            Word 0: 0x08000000 | ((target_addr >> 2) & 0x03FFFFFF)
            Word 1: 0x00000000 (nop)
        """
        fn = self.find_import(lib_name, nid_or_name)
        if not fn:
            raise KeyError(
                f"Import function {nid_or_name!r} not found in library {lib_name!r}"
            )
        if fn.stub_offset == 0:
            raise ValueError(
                f"Import function {nid_or_name!r} has no valid stub code offset"
            )

        # MIPS 'j' opcode: upper 6 bits = 000010 (0x08), lower 26 bits = target >> 2
        jump_opcode = 0x08000000 | ((target_addr >> 2) & 0x03FFFFFF)
        nop_opcode = 0x00000000

        self.raw_data[fn.stub_offset : fn.stub_offset + 4] = jump_opcode.to_bytes(
            4, "little"
        )
        self.raw_data[fn.stub_offset + 4 : fn.stub_offset + 8] = nop_opcode.to_bytes(
            4, "little"
        )

    def replace_import_nid(
        self,
        lib_name: str,
        old_nid_or_name: Union[int, str],
        new_nid_or_name: Union[int, str],
    ):
        """
        Replace an imported function or variable's NID in the PRX NID table.
        Allows substituting one system function call or variable with another.
        """
        target = self.find_import(lib_name, old_nid_or_name)
        if not target:
            target = self.find_import_variable(lib_name, old_nid_or_name)
            if not target:
                raise KeyError(
                    f"Import symbol {old_nid_or_name!r} not found in library {lib_name!r}"
                )

        new_nid = (
            new_nid_or_name
            if isinstance(new_nid_or_name, int)
            else PSPNIDResolver.resolve_name(new_nid_or_name)
        )

        self.raw_data[target.nid_offset : target.nid_offset + 4] = new_nid.to_bytes(4, "little")
        target.nid = new_nid
        target.name = PSPNIDResolver.resolve_nid(new_nid) or (
            new_nid_or_name if isinstance(new_nid_or_name, str) else None
        )


def create_synthetic_prx(
    module_name: str = "SYNTH_PRX",
    major_version: int = 1,
    minor_version: int = 0,
    is_kernel_mode: bool = False,
    imported_libs: Optional[Dict[str, List[str]]] = None,
    exported_functions: Optional[List[Tuple[str, int]]] = None,
    imported_variables: Optional[Dict[str, List[str]]] = None,
) -> bytes:
    """
    Construct a valid synthetic 32-bit Little-Endian MIPS ELF PRX binary for testing.
    Includes ELF header, section headers, .text, .rodata, sceModuleInfo, export table,
    import stub table, and section header string table.
    """
    if imported_libs is None:
        imported_libs = {
            "sceDisplay_driver": ["sceDisplayWaitVblankStart", "sceDisplaySetMode"],
            "sceIo_driver": ["sceIoOpen", "sceIoRead"],
        }
    if exported_functions is None:
        exported_functions = [
            ("module_start", 0x08900000),
            ("module_stop", 0x08900020),
        ]
    if imported_variables is None:
        imported_variables = {}

    all_import_libs = list(imported_libs.keys())
    for lib in imported_variables.keys():
        if lib not in all_import_libs:
            all_import_libs.append(lib)

    buf = bytearray()

    # Reserve ELF Header (52 bytes)
    buf.extend(b"\x00" * 52)

    # 1. Section: .text (32 bytes dummy MIPS code: jr $ra; nop)
    text_offset = len(buf)
    text_data = b"\x08\x00\xe0\x03\x00\x00\x00\x00" * 4  # 32 bytes
    buf.extend(text_data)
    text_size = len(text_data)

    # 2. Section: .rodata (Strings for module name, library names, etc.)
    rodata_offset = len(buf)
    name_strings = io.BytesIO()

    def add_string(s: str) -> int:
        pos = name_strings.tell()
        name_strings.write(s.encode("ascii") + b"\x00")
        return rodata_offset + pos

    # Pre-encode strings
    lib_name_offsets = {}
    for lib_name in all_import_libs:
        lib_name_offsets[lib_name] = add_string(lib_name)
    syslib_offset = add_string("syslib")

    rodata_data = name_strings.getvalue()
    buf.extend(rodata_data)
    rodata_size = len(rodata_data)

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 3. Section: .rodata.sceResEnt (Export Library Entries)
    resent_offset = len(buf)
    # Entry table for syslib
    # func_count NIDs, var_count NIDs, func_count ptrs, var_count ptrs
    syslib_entry_tbl_offset = resent_offset + 16
    func_count = len(exported_functions)
    export_nids = [PSPNIDResolver.calculate_nid(name) for name, _ in exported_functions]
    export_ptrs = [ptr for _, ptr in exported_functions]

    # Write SceLibraryEntryStruct (16 bytes)
    ent_struct = SceLibraryEntryStruct()
    ent_struct.name_addr = syslib_offset
    ent_struct.version = 0x0001
    ent_struct.attribute = 0x8000  # syslib
    ent_struct.ent_len = 4  # 16 bytes
    ent_struct.var_count = 0
    ent_struct.func_count = func_count
    ent_struct.entry_table = syslib_entry_tbl_offset
    buf.extend(ent_struct.to_bytes(endian="<"))

    # Write export entry table
    for nid in export_nids:
        buf.extend(nid.to_bytes(4, "little"))
    for ptr in export_ptrs:
        buf.extend(ptr.to_bytes(4, "little"))

    resent_size = len(buf) - resent_offset

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 4. Section: .rodata.sceStub.text (MIPS call stubs: 8 bytes per import func / var)
    stub_text_offset = len(buf)
    total_funcs = sum(len(imported_libs.get(lib, [])) for lib in all_import_libs)
    total_vars = sum(len(imported_variables.get(lib, [])) for lib in all_import_libs)
    stub_text_data = b"\x08\x00\xe0\x03\x00\x00\x00\x00" * (total_funcs + total_vars)
    buf.extend(stub_text_data)
    stub_text_size = len(stub_text_data)

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 5. Section: .rodata.sceNID (Import NIDs)
    nid_sec_offset = len(buf)
    import_lib_nid_offsets = {}
    import_lib_stub_offsets = {}
    import_lib_vstub_offsets = {}
    cur_stub_text_pos = stub_text_offset

    for lib_name in all_import_libs:
        import_lib_nid_offsets[lib_name] = len(buf)
        import_lib_stub_offsets[lib_name] = cur_stub_text_pos
        funcs = imported_libs.get(lib_name, [])
        for func_name in funcs:
            fn_nid = PSPNIDResolver.calculate_nid(func_name)
            buf.extend(fn_nid.to_bytes(4, "little"))
            cur_stub_text_pos += 8

        vars_list = imported_variables.get(lib_name, [])
        import_lib_vstub_offsets[lib_name] = cur_stub_text_pos
        for var_name in vars_list:
            vn_nid = PSPNIDResolver.calculate_nid(var_name)
            buf.extend(vn_nid.to_bytes(4, "little"))
            cur_stub_text_pos += 8

    nid_sec_size = len(buf) - nid_sec_offset

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 6. Import Stub Table (.rodata.sceStub)
    stub_table_offset = len(buf)
    for lib_name in all_import_libs:
        funcs = imported_libs.get(lib_name, [])
        vars_list = imported_variables.get(lib_name, [])
        has_vars = len(vars_list) > 0

        stub_entry = SceLibraryStubStruct()
        stub_entry.name_addr = lib_name_offsets[lib_name]
        stub_entry.version = 0x0001
        stub_entry.flags = 0x0000
        stub_entry.stub_len = 6 if has_vars else 5  # 24 bytes vs 20 bytes
        stub_entry.var_count = len(vars_list)
        stub_entry.func_count = len(funcs)
        stub_entry.nid_table = import_lib_nid_offsets[lib_name]
        stub_entry.stub_table = import_lib_stub_offsets[lib_name] if len(funcs) > 0 else 0
        buf.extend(stub_entry.to_bytes(endian="<"))
        if has_vars:
            vstub_addr = import_lib_vstub_offsets[lib_name]
            buf.extend(vstub_addr.to_bytes(4, "little"))

    stub_table_size = len(buf) - stub_table_offset

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 7. Section: .rodata.sceModuleInfo (52 bytes)
    modinfo_offset = len(buf)
    modinfo = SceModuleInfoStruct()
    modinfo.modattribute = 0x1000 if is_kernel_mode else 0x0000
    modinfo.modversion_minor = minor_version
    modinfo.modversion_major = major_version
    name_bytes = module_name.encode("ascii")[:27]
    modinfo.modname = name_bytes + b"\x00" * (28 - len(name_bytes))
    modinfo.gp_value = 0x08900000
    modinfo.ent_top = resent_offset
    modinfo.ent_end = resent_offset + 16
    modinfo.stub_top = stub_table_offset
    modinfo.stub_end = stub_table_offset + stub_table_size
    buf.extend(modinfo.to_bytes(endian="<"))
    modinfo_size = len(buf) - modinfo_offset

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 8. Section: .shstrtab (Section Header String Table)
    shstrtab_offset = len(buf)
    sec_names = [
        "",
        ".text",
        ".rodata",
        ".rodata.sceResEnt",
        ".rodata.sceStub.text",
        ".rodata.sceNID",
        ".rodata.sceStub",
        ".rodata.sceModuleInfo",
        ".shstrtab",
    ]
    shstrtab_builder = io.BytesIO()
    sec_name_indices = []
    for s in sec_names:
        pos = shstrtab_builder.tell()
        shstrtab_builder.write(s.encode("ascii") + b"\x00")
        sec_name_indices.append(pos)
    shstrtab_data = shstrtab_builder.getvalue()
    buf.extend(shstrtab_data)
    shstrtab_size = len(shstrtab_data)

    # Align 4
    while len(buf) % 4 != 0:
        buf.append(0)

    # 9. Section Header Table (shnum * 40 bytes)
    shoff = len(buf)
    sections_info = [
        # (sh_name_idx, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_align, sh_entsize)
        (sec_name_indices[0], SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0),
        (
            sec_name_indices[1],
            SHT_PROGBITS,
            6,
            text_offset,
            text_offset,
            text_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[2],
            SHT_PROGBITS,
            2,
            rodata_offset,
            rodata_offset,
            rodata_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[3],
            SHT_PROGBITS,
            2,
            resent_offset,
            resent_offset,
            resent_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[4],
            SHT_PROGBITS,
            6,
            stub_text_offset,
            stub_text_offset,
            stub_text_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[5],
            SHT_PROGBITS,
            2,
            nid_sec_offset,
            nid_sec_offset,
            nid_sec_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[6],
            SHT_PROGBITS,
            2,
            stub_table_offset,
            stub_table_offset,
            stub_table_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[7],
            SHT_PROGBITS,
            2,
            modinfo_offset,
            modinfo_offset,
            modinfo_size,
            0,
            0,
            4,
            0,
        ),
        (
            sec_name_indices[8],
            SHT_STRTAB,
            0,
            shstrtab_offset,
            shstrtab_offset,
            shstrtab_size,
            0,
            0,
            1,
            0,
        ),
    ]

    for s in sections_info:
        sec_hdr = Elf32SectionHeaderStruct()
        sec_hdr.sh_name = s[0]
        sec_hdr.sh_type = s[1]
        sec_hdr.sh_flags = s[2]
        sec_hdr.sh_addr = s[3]
        sec_hdr.sh_offset = s[4]
        sec_hdr.sh_size = s[5]
        sec_hdr.sh_link = s[6]
        sec_hdr.sh_info = s[7]
        sec_hdr.sh_addralign = s[8]
        sec_hdr.sh_entsize = s[9]
        buf.extend(sec_hdr.to_bytes(endian="<"))

    # Write ELF32 Header at offset 0
    elf_hdr = Elf32HeaderStruct()
    elf_hdr.e_ident_magic = ELF_MAGIC
    elf_hdr.e_ident_class = 1  # 32-bit
    elf_hdr.e_ident_data = 1  # Little-endian
    elf_hdr.e_ident_version = 1
    elf_hdr.e_ident_osabi = 0
    elf_hdr.e_ident_abiversion = 0
    elf_hdr.e_ident_pad = b"\x00" * 7
    elf_hdr.e_type = ET_SCE_EXEC
    elf_hdr.e_machine = EM_MIPS
    elf_hdr.e_version = 1
    elf_hdr.e_entry = text_offset
    elf_hdr.e_phoff = 0
    elf_hdr.e_shoff = shoff
    elf_hdr.e_flags = 0x10000000  # MIPS PIC
    elf_hdr.e_ehsize = 52
    elf_hdr.e_phentsize = 0
    elf_hdr.e_phnum = 0
    elf_hdr.e_shentsize = 40
    elf_hdr.e_shnum = len(sections_info)
    elf_hdr.e_shstrndx = 8  # index of .shstrtab

    buf[:52] = elf_hdr.to_bytes(endian="<")

    return bytes(buf)
