import io
from miorom.errors import ParseError
import os
import struct
from typing import Dict, List, Optional, Tuple

from miorom.platforms.cdrom.cue import CueSheet, CueTrack, lba_to_msf
from miorom.platforms.iso.iso9660 import ISO9660

# Precomputed CD-ROM EDC table
EDC_TABLE = []
for i in range(256):
    edc = i
    for _ in range(8):
        if edc & 1:
            edc = (edc >> 1) ^ 0xD8018001
        else:
            edc >>= 1
    EDC_TABLE.append(edc)


def calculate_cdrom_edc(data: bytes) -> int:
    """Calculate standard 32-bit CD-ROM EDC checksum over sector data."""
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ EDC_TABLE[(edc ^ b) & 0xFF]
    return edc


def _to_bcd(val: int) -> int:
    """Convert integer to Binary Coded Decimal (BCD)."""
    return ((val // 10) << 4) | (val % 10)


SYNC_PATTERN = b"\x00" + b"\xFF" * 10 + b"\x00"


class CueBinDisc:
    """
    Multi-Track CD-ROM Disc Virtual Engine.
    Handles multi-track CUE/BIN images (PS1, Sega Saturn, Sega CD, PC Engine CD),
    LBA sector translation, data track ISO stripping & re-building,
    and CD-DA audio track export/import to standard 16-bit 44.1kHz WAV.
    """

    def __init__(self, cue: CueSheet, bin_buffers: Dict[str, bytearray]):
        self.cue = cue
        self.bin_buffers = bin_buffers
        self._calculate_track_spans()

    @classmethod
    def load(cls, cue_path: str) -> "CueBinDisc":
        """Load a CD disc image from a .cue file and its referenced .bin files."""
        cue = CueSheet.from_file(cue_path)
        base_dir = os.path.dirname(os.path.abspath(cue_path))
        buffers = {}

        for file_entry in cue.files:
            bin_name = file_entry[0]
            bin_path = os.path.join(base_dir, bin_name)
            if not os.path.exists(bin_path):
                # Fallback: check case-insensitive match in folder
                matched = False
                for item in os.listdir(base_dir):
                    if item.lower() == bin_name.lower():
                        bin_path = os.path.join(base_dir, item)
                        matched = True
                        break
                if not matched:
                    raise FileNotFoundError(f"Referenced BIN file not found: '{bin_name}' at {base_dir}")

            with open(bin_path, "rb") as f:
                buffers[bin_name] = bytearray(f.read())

        return cls(cue, buffers)

    @classmethod
    def from_tracks(cls, cue: CueSheet, bin_data_map: Dict[str, bytes]) -> "CueBinDisc":
        """Construct CueBinDisc in-memory from a CueSheet and dictionary of bin bytes."""
        buffers = {k: bytearray(v) for k, v in bin_data_map.items()}
        return cls(cue, buffers)

    def _calculate_track_spans(self):
        """Compute absolute LBA and sector bounds for each track."""
        current_lba = 0
        for file_name, file_type, tracks in self.cue.files:
            buf = self.bin_buffers.get(file_name, bytearray())
            is_multi_track_single_bin = len(tracks) > 1

            for i, trk in enumerate(tracks):
                trk.start_lba = current_lba
                sec_size = trk.sector_size

                if is_multi_track_single_bin:
                    idx1_lba = trk.indexes.get(1, trk.indexes.get(0, 0))
                    start_byte = idx1_lba * sec_size
                    if i + 1 < len(tracks):
                        next_trk = tracks[i + 1]
                        next_idx = next_trk.indexes.get(0, next_trk.indexes.get(1, 0))
                        end_byte = next_idx * next_trk.sector_size
                    else:
                        end_byte = len(buf)
                    track_bytes = max(0, end_byte - start_byte)
                    trk.sector_count = track_bytes // sec_size
                else:
                    # Single track in this file
                    trk.sector_count = len(buf) // sec_size

                current_lba += trk.sector_count

    @property
    def track_count(self) -> int:
        return len(self.cue.tracks)

    def get_track(self, track_number: int) -> CueTrack:
        """Find track by 1-indexed track number."""
        for trk in self.cue.tracks:
            if trk.number == track_number:
                return trk
        raise ParseError(f"Track {track_number} does not exist in CUE sheet.")

    def _get_track_byte_slice(self, track: CueTrack) -> Tuple[str, int, int]:
        """Return (bin_file_name, start_byte, byte_length) for given track."""
        buf = self.bin_buffers[track.file_name]
        # Find index in file's track list
        for file_name, _, tracks in self.cue.files:
            if file_name == track.file_name:
                if len(tracks) == 1:
                    return file_name, 0, len(buf)
                else:
                    idx = tracks.index(track)
                    start_lba = track.indexes.get(1, track.indexes.get(0, 0))
                    start_byte = start_lba * track.sector_size
                    if idx + 1 < len(tracks):
                        next_trk = tracks[idx + 1]
                        next_start_lba = next_trk.indexes.get(0, next_trk.indexes.get(1, 0))
                        end_byte = next_start_lba * next_trk.sector_size
                    else:
                        end_byte = len(buf)
                    return file_name, start_byte, max(0, end_byte - start_byte)
        return track.file_name, 0, len(buf)

    def read_sector(self, track_number: int, sector_idx: int, raw: bool = True) -> bytes:
        """
        Read a single sector from a track.
        If raw=False on MODE1/MODE2, strips headers/ECC and returns user data (2048 bytes).
        """
        trk = self.get_track(track_number)
        fn, start_byte, length = self._get_track_byte_slice(trk)
        sec_size = trk.sector_size
        offset = start_byte + sector_idx * sec_size
        buf = self.bin_buffers[fn]

        if offset + sec_size > len(buf):
            raise IndexError(f"Sector {sector_idx} out of range for track {track_number}.")

        sec = bytes(buf[offset:offset + sec_size])
        if raw or not trk.is_data_track:
            return sec

        # User data stripping
        if trk.track_type == "MODE1/2352":
            return sec[16:2064]
        elif trk.track_type == "MODE2/2352":
            # Check submode byte at offset 18
            submode = sec[18]
            is_form2 = (submode & 0x20) != 0
            if is_form2:
                return sec[24:2348]  # Form 2: 2324 bytes
            return sec[24:2072]      # Form 1: 2048 bytes
        elif trk.track_type == "MODE1/2048":
            return sec
        return sec

    def extract_track_data(self, track_number: int, raw: bool = False) -> bytes:
        """
        Extract the full content of a track.
        If raw=False on a data track, strips headers/ECC into a pure 2048-byte/sector ISO image.
        """
        trk = self.get_track(track_number)
        fn, start_byte, length = self._get_track_byte_slice(trk)
        buf = self.bin_buffers[fn]
        track_raw = buf[start_byte:start_byte + length]

        if raw or not trk.is_data_track or trk.track_type == "MODE1/2048":
            return bytes(track_raw)

        sec_size = trk.sector_size
        num_sectors = len(track_raw) // sec_size
        stripped = bytearray()

        for i in range(num_sectors):
            sec = track_raw[i * sec_size:(i + 1) * sec_size]
            if trk.track_type == "MODE1/2352":
                stripped.extend(sec[16:2064])
            elif trk.track_type == "MODE2/2352":
                submode = sec[18]
                is_form2 = (submode & 0x20) != 0
                if is_form2:
                    stripped.extend(sec[24:2348])
                else:
                    stripped.extend(sec[24:2072])
            else:
                stripped.extend(sec)

        return bytes(stripped)

    def replace_track_data(self, track_number: int, new_data: bytes, is_raw: bool = False):
        """
        Replace track data. If is_raw=False on a MODE1/2352 track, packages 2048-byte chunks
        into compliant 2352-byte sectors with sync, MSF header, EDC, and padding.
        """
        trk = self.get_track(track_number)
        fn, start_byte, length = self._get_track_byte_slice(trk)

        if is_raw or not trk.is_data_track or trk.track_type == "MODE1/2048":
            packed_bytes = new_data
        else:
            # Build 2352 sectors from 2048-byte chunks
            chunk_size = 2048
            num_sectors = (len(new_data) + chunk_size - 1) // chunk_size
            packed = bytearray()

            for i in range(num_sectors):
                chunk = new_data[i * chunk_size:(i + 1) * chunk_size]
                if len(chunk) < chunk_size:
                    chunk = chunk + b"\x00" * (chunk_size - len(chunk))

                # Standard CD pregap offset = 150 sectors (00:02:00)
                lba = trk.start_lba + i + 150
                m, s, f = lba_to_msf(lba)

                header = bytes([_to_bcd(m), _to_bcd(s), _to_bcd(f), 0x01])  # Mode 1
                sector_core = header + chunk  # 2052 bytes
                edc = calculate_cdrom_edc(sector_core)

                sector = bytearray(2352)
                sector[0:12] = SYNC_PATTERN
                sector[12:16] = header
                sector[16:2064] = chunk
                struct.pack_into("<I", sector, 2064, edc)
                # bytes 2068..2352: zero reserved + ECC
                packed.extend(sector)

            packed_bytes = bytes(packed)

        # Replace in bin buffer
        buf = self.bin_buffers[fn]
        buf[start_byte:start_byte + length] = packed_bytes
        self._calculate_track_spans()

    def export_audio_track_wav(self, track_number: int, out_path: Optional[str] = None) -> bytes:
        """
        Export a CD-DA audio track to standard 16-bit 44.1kHz stereo PCM WAV file.
        """
        trk = self.get_track(track_number)
        if not trk.is_audio_track:
            raise ParseError(f"Track {track_number} is not an AUDIO track ({trk.track_type}).")

        pcm_data = self.extract_track_data(track_number, raw=True)

        # WAV RIFF header (PCM 44.1kHz 16-bit stereo)
        fmt_chunk = struct.pack("<HHIIHH", 1, 2, 44100, 176400, 4, 16)
        data_len = len(pcm_data)
        riff_len = 4 + (8 + len(fmt_chunk)) + (8 + data_len)

        wav = bytearray()
        wav.extend(b"RIFF")
        wav.extend(struct.pack("<I", riff_len))
        wav.extend(b"WAVE")
        wav.extend(b"fmt ")
        wav.extend(struct.pack("<I", len(fmt_chunk)))
        wav.extend(fmt_chunk)
        wav.extend(b"data")
        wav.extend(struct.pack("<I", data_len))
        wav.extend(pcm_data)

        res = bytes(wav)
        if out_path:
            with open(out_path, "wb") as f:
                f.write(res)

        return res

    def import_audio_track_wav(self, track_number: int, wav_data: bytes):
        """
        Import 16-bit 44.1kHz stereo PCM WAV file data into a CD-DA audio track.
        """
        trk = self.get_track(track_number)
        if not trk.is_audio_track:
            raise ParseError(f"Track {track_number} is not an AUDIO track.")

        if len(wav_data) < 44 or wav_data[:4] != b"RIFF" or wav_data[8:12] != b"WAVE":
            raise ParseError("Invalid WAV file: missing RIFF/WAVE header.")

        offset = 12
        pcm_bytes = None
        while offset + 8 <= len(wav_data):
            chunk_id = wav_data[offset:offset + 4]
            chunk_sz = struct.unpack_from("<I", wav_data, offset + 4)[0]
            chunk_data = wav_data[offset + 8:offset + 8 + chunk_sz]

            if chunk_id == b"data":
                pcm_bytes = chunk_data
                break
            offset += 8 + ((chunk_sz + 1) & ~1)

        if pcm_bytes is None:
            raise ParseError("Invalid WAV file: no 'data' chunk found.")

        # Align to 2352 bytes
        rem = len(pcm_bytes) % 2352
        if rem != 0:
            pcm_bytes = pcm_bytes + b"\x00" * (2352 - rem)

        self.replace_track_data(track_number, pcm_bytes, is_raw=True)

    def to_iso(self, track_number: int = 1) -> ISO9660:
        """
        Extract track as stripped 2048-byte/sector ISO and return an ISO9660 filesystem object.
        """
        iso_data = self.extract_track_data(track_number, raw=False)
        return ISO9660(iso_data)

    def save(self, cue_path: str, bin_paths: Optional[Dict[str, str]] = None):
        """Save CUE sheet and modified BIN files to disk."""
        base_dir = os.path.dirname(os.path.abspath(cue_path))
        os.makedirs(base_dir, exist_ok=True)

        # Write CUE
        with open(cue_path, "w", encoding="utf-8") as f:
            f.write(self.cue.to_string())

        # Write BIN files
        for fn, buf in self.bin_buffers.items():
            target_path = bin_paths.get(fn) if bin_paths else os.path.join(base_dir, fn)
            with open(target_path, "wb") as f:
                f.write(buf)
