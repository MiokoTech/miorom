"""
miorom.debug.gdb_client
~~~~~~~~~~~~~~~~~~~~~~~
Universal GDB Remote Serial Protocol (RSP) client for emulator dynamic analysis.
Enables live memory inspection, hardware watchpoints (break on write/read),
register reading, and string tracing across mGBA, No$gba, MelonDS, PCSX-Redux,
Dolphin, Citra, and QEMU.
"""

from miorom.errors import ParseError
from miorom.result import MioRomResult
import socket
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.debug.client import EmulatorClient


@dataclass
class StopReason(MioRomResult):
    """Represents a target halt event (e.g. watchpoint hit or breakpoint)."""
    signal: int
    reason: str
    address: Optional[int] = None
    raw_packet: str = ""


class GDBProtocolMock:
    """
    In-memory mock server simulating GDB Remote Serial Protocol for testing.
    """

    def __init__(self, ram_size: int = 4 * 1024 * 1024, base_address: int = 0x02000000):
        self.base_address = base_address
        self.ram = bytearray(ram_size)
        self.registers = [0] * 16  # R0..R15 for ARM
        self.registers[15] = base_address  # PC
        self.watchpoints: Dict[int, int] = {}  # addr -> size
        self.breakpoints: List[int] = []
        self.last_signal = 5  # SIGTRAP

    def handle_command(self, cmd: str) -> str:
        if cmd == "?":
            return "S05"
        elif cmd.startswith("m"):
            # m<addr>,<len>
            parts = cmd[1:].split(",")
            addr = int(parts[0], 16)
            length = int(parts[1], 16)
            offset = addr - self.base_address
            if 0 <= offset and offset + length <= len(self.ram):
                return self.ram[offset : offset + length].hex()
            return "E01"
        elif cmd.startswith("M"):
            # M<addr>,<len>:<data>
            header, hex_data = cmd[1:].split(":")
            addr, length = [int(p, 16) for p in header.split(",")]
            offset = addr - self.base_address
            raw = bytes.fromhex(hex_data)
            if 0 <= offset and offset + len(raw) <= len(self.ram):
                self.ram[offset : offset + len(raw)] = raw
                return "OK"
            return "E01"
        elif cmd.startswith("p"):
            reg_idx = int(cmd[1:], 16)
            if 0 <= reg_idx < len(self.registers):
                # Little-endian 32-bit hex
                val = self.registers[reg_idx]
                return struct.pack("<I", val).hex()
            return "E01"
        elif cmd.startswith("P"):
            # P<reg>=<val>
            reg_s, val_s = cmd[1:].split("=")
            reg_idx = int(reg_s, 16)
            val = struct.unpack("<I", bytes.fromhex(val_s))[0]
            if 0 <= reg_idx < len(self.registers):
                self.registers[reg_idx] = val
                return "OK"
            return "E01"
        elif cmd.startswith("Z2,"):
            # Z2,<addr>,<kind> (write watchpoint)
            parts = cmd[3:].split(",")
            addr = int(parts[0], 16)
            kind = int(parts[1], 16)
            self.watchpoints[addr] = kind
            return "OK"
        elif cmd.startswith("z2,"):
            parts = cmd[3:].split(",")
            addr = int(parts[0], 16)
            self.watchpoints.pop(addr, None)
            return "OK"
        elif cmd.startswith("Z0,"):
            # Software breakpoint
            parts = cmd[3:].split(",")
            addr = int(parts[0], 16)
            if addr not in self.breakpoints:
                self.breakpoints.append(addr)
            return "OK"
        elif cmd.startswith("z0,"):
            parts = cmd[3:].split(",")
            addr = int(parts[0], 16)
            if addr in self.breakpoints:
                self.breakpoints.remove(addr)
            return "OK"
        elif cmd == "c":
            return "T05watch:" + f"{list(self.watchpoints.keys())[0]:x};" if self.watchpoints else "S05"
        return ""


class GDBEmulatorClient(EmulatorClient):
    """
    Client connecting to an emulator via standard GDB Remote Serial Protocol (RSP).
    Compatible with mGBA, MelonDS, No$gba, PCSX-Redux, Dolphin, and Citra.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3333,
        mock: Optional[GDBProtocolMock] = None,
        timeout: float = 2.0,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.mock = mock
        self._sock: Optional[socket.socket] = None

    @classmethod
    def with_mock(cls, ram_size: int = 4 * 1024 * 1024, base_address: int = 0x02000000) -> "GDBEmulatorClient":
        """Creates a GDBEmulatorClient connected to a virtual in-memory mock."""
        mock = GDBProtocolMock(ram_size=ram_size, base_address=base_address)
        return cls(mock=mock)

    def connect(self) -> None:
        """Connects to the GDB stub socket if not running in mock mode."""
        if self.mock is not None:
            return
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    @staticmethod
    def _checksum(data: str) -> int:
        return sum(data.encode("latin1")) % 256

    def send_packet(self, command: str) -> str:
        """
        Sends an RSP packet ($<cmd>#<chk>) and reads the response.
        """
        if self.mock is not None:
            return self.mock.handle_command(command)

        self.connect()
        assert self._sock is not None

        chk = self._checksum(command)
        packet = f"${command}#{chk:02x}"
        self._sock.sendall(packet.encode("latin1"))

        # Wait for ACK '+'
        ack = self._sock.recv(1)
        if ack != b"+":
            # Protocol out of sync or NACK
            pass

        # Read response packet ($...#xx)
        resp_buf = bytearray()
        in_packet = False
        while True:
            ch = self._sock.recv(1)
            if not ch:
                break
            if ch == b"$":
                in_packet = True
                resp_buf.clear()
            elif in_packet:
                if ch == b"#":
                    # Read 2 checksum bytes
                    _ = self._sock.recv(2)
                    # Send ACK '+'
                    self._sock.sendall(b"+")
                    break
                resp_buf.extend(ch)

        return resp_buf.decode("latin1", errors="replace")

    def read_bytes(self, address: int, size: int) -> bytes:
        """Reads raw bytes from target memory space."""
        resp = self.send_packet(f"m{address:x},{size:x}")
        if resp.startswith("E"):
            raise ParseError(f"GDB memory read error at 0x{address:08X}: {resp}")
        return bytes.fromhex(resp)

    def write_bytes(self, address: int, data: bytes) -> None:
        """Writes raw bytes to target memory space."""
        hex_str = data.hex()
        resp = self.send_packet(f"M{address:x},{len(data):x}:{hex_str}")
        if resp != "OK":
            raise ParseError(f"GDB memory write error at 0x{address:08X}: {resp}")

    def read_register(self, reg_num: int) -> int:
        """Reads a 32-bit CPU register value."""
        resp = self.send_packet(f"p{reg_num:x}")
        if resp.startswith("E") or not resp:
            raise ParseError(f"Failed to read register R{reg_num}: {resp}")
        raw = bytes.fromhex(resp)
        return struct.unpack("<I", raw)[0]

    def write_register(self, reg_num: int, value: int) -> None:
        """Writes a 32-bit CPU register value."""
        hex_val = struct.pack("<I", value).hex()
        resp = self.send_packet(f"P{reg_num:x}={hex_val}")
        if resp != "OK":
            raise ParseError(f"Failed to write register R{reg_num}: {resp}")

    def set_watchpoint(self, address: int, size: int = 4, kind: str = "write") -> bool:
        """
        Sets a hardware watchpoint:
        'write' (Z2), 'read' (Z3), or 'access' (Z4).
        """
        cmd_type = "Z2" if kind == "write" else ("Z3" if kind == "read" else "Z4")
        resp = self.send_packet(f"{cmd_type},{address:x},{size:x}")
        return resp == "OK"

    def remove_watchpoint(self, address: int, size: int = 4, kind: str = "write") -> bool:
        cmd_type = "z2" if kind == "write" else ("z3" if kind == "read" else "z4")
        resp = self.send_packet(f"{cmd_type},{address:x},{size:x}")
        return resp == "OK"

    def set_breakpoint(self, address: int) -> bool:
        """Sets an execution software breakpoint (Z0)."""
        resp = self.send_packet(f"Z0,{address:x},4")
        return resp == "OK"

    def remove_breakpoint(self, address: int) -> bool:
        resp = self.send_packet(f"z0,{address:x},4")
        return resp == "OK"

    def continue_execution(self) -> StopReason:
        """
        Resumes game execution until a watchpoint or breakpoint halts the CPU.
        """
        resp = self.send_packet("c")
        if resp.startswith("T"):
            # Format: T<signal><key:val;...>
            sig = int(resp[1:3], 16)
            addr = None
            if "watch:" in resp:
                part = resp.split("watch:")[1].split(";")[0]
                addr = int(part, 16)
            return StopReason(signal=sig, reason="watchpoint_hit", address=addr, raw_packet=resp)
        elif resp.startswith("S"):
            sig = int(resp[1:3], 16)
            return StopReason(signal=sig, reason="breakpoint_hit", raw_packet=resp)
        return StopReason(signal=0, reason="unknown", raw_packet=resp)

    def find_bytes_in_ram(
        self,
        pattern: bytes,
        start_addr: int,
        end_addr: int,
        chunk_size: int = 4096,
    ) -> List[int]:
        """
        Scans emulator RAM between start_addr and end_addr for a raw byte pattern.
        Handles chunk boundaries seamlessly without missing boundary-spanning patterns.
        """
        if not pattern or start_addr >= end_addr:
            return []
        matches: List[int] = []
        pat_len = len(pattern)
        cur = start_addr
        overlap = b""

        while cur < end_addr:
            read_len = min(chunk_size, end_addr - cur)
            chunk = self.read_bytes(cur, read_len)
            block = overlap + chunk
            block_base = cur - len(overlap)

            pos = 0
            while True:
                idx = block.find(pattern, pos)
                if idx == -1:
                    break
                match_addr = block_base + idx
                if match_addr >= start_addr and match_addr + pat_len <= end_addr:
                    if not matches or matches[-1] != match_addr:
                        matches.append(match_addr)
                pos = idx + 1

            if pat_len > 1:
                overlap = block[-(pat_len - 1):]
            else:
                overlap = b""
            cur += read_len

        return matches

    def find_string_in_ram(
        self,
        query: str,
        start_addr: int,
        end_addr: int,
        encoding: str = "utf-8",
        charmap: Optional[Any] = None,
        chunk_size: int = 4096,
    ) -> List[int]:
        """
        Searches live emulator RAM for an encoded string or charmap-mapped tokens.
        """
        if charmap is not None:
            pattern = charmap.encode(query)
        else:
            pattern = query.encode(encoding)
        return self.find_bytes_in_ram(pattern, start_addr, end_addr, chunk_size=chunk_size)

    def find_pointers_to_in_ram(
        self,
        target_address: int,
        start_addr: int,
        end_addr: int,
        endian: str = "<",
        pointer_size: int = 4,
        chunk_size: int = 4096,
    ) -> List[int]:
        """
        Searches live emulator RAM for 16-bit or 32-bit pointers pointing to target_address.
        """
        fmt = f"{endian}I" if pointer_size == 4 else f"{endian}H"
        pattern = struct.pack(fmt, target_address)
        return self.find_bytes_in_ram(pattern, start_addr, end_addr, chunk_size=chunk_size)

    def dump_ram_range(
        self,
        start_addr: int,
        size: int,
        output_path: Optional[str] = None,
        chunk_size: int = 4096,
    ) -> bytes:
        """
        Dumps a contiguous block of RAM from the emulator into bytes and optionally writes to a file.
        """
        data = bytearray()
        cur = start_addr
        end_addr = start_addr + size
        while cur < end_addr:
            read_len = min(chunk_size, end_addr - cur)
            data.extend(self.read_bytes(cur, read_len))
            cur += read_len
        res = bytes(data)
        if output_path:
            with open(output_path, "wb") as f:
                f.write(res)
        return res
