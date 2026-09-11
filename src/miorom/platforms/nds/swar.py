"""
swar.py - Nintendo DS Nitro Sound Wave Archive (SWAR) and Sound Wave (SWAV) parser,
extractor, and rebuilder.

Supports:
- Extracting instrument and sound effect waveform samples from .swar archives to standard 16-bit PCM .wav files.
- Preserving loop points and sample rates.
- Rebuilding pristine binary .swar archives with updated/injected .wav audio samples.
"""

from __future__ import annotations

import json
import math
import os
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from miorom.audio.adpcm import ADPCMCodec
from miorom.errors import ParseError


@dataclass
class SWAVEntry:
    """Individual sound wave sample inside an SWAR container."""

    index: int
    offset: int
    size: int
    wave_type: int  # 0: PCM8, 1: PCM16, 2: IMA-ADPCM
    loop_flag: int  # 0: Non-looping, 1: Looping
    sample_rate: int
    timer_period: int
    loop_start_words: int  # in 32-bit words
    loop_len_words: int    # in 32-bit words
    payload: bytes

    def decode_samples(self) -> List[int]:
        """Decodes the sample payload into signed 16-bit PCM audio samples."""
        total_payload_len = len(self.payload)
        if total_payload_len == 0:
            return []

        if self.wave_type == 2:
            # IMA-ADPCM 4-bit
            if total_payload_len < 4:
                return []
            init_sample, init_index = struct.unpack_from("<hb", self.payload, 0)
            init_index = max(0, min(88, init_index))
            adpcm_data = self.payload[4:]
            samples = ADPCMCodec.decode_ima(
                adpcm_data, initial_predictor=init_sample, initial_index=init_index
            )
            # Total samples in ADPCM: (len(adpcm_data)) * 2
            total_samples = len(adpcm_data) * 2
            return samples[:total_samples]

        elif self.wave_type == 1:
            # PCM16 signed Little Endian
            sample_count = total_payload_len // 2
            return list(struct.unpack(f"<{sample_count}h", self.payload[: sample_count * 2]))

        elif self.wave_type == 0:
            # PCM8 signed
            sample_count = total_payload_len
            raw_samps = struct.unpack(f"<{sample_count}b", self.payload[:sample_count])
            return [s << 8 for s in raw_samps]

        else:
            raise ValueError(f"Unsupported SWAV wave_type: {self.wave_type}")

    def to_wav(self) -> bytes:
        """Decodes the sample into a standard 16-bit PCM RIFF WAV container."""
        samples = self.decode_samples()
        return ADPCMCodec.build_wav(
            samples,
            sample_rate=self.sample_rate if self.sample_rate > 0 else 22050,
            channels=1,
        )

    def save_wav(self, output_path: str) -> None:
        """Saves the decoded sample to a .wav file on disk."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(self.to_wav())

    @classmethod
    def from_wav(
        cls,
        wav_bytes: bytes,
        wave_type: int = 2,
        loop_flag: int = 0,
        loop_start_samples: int = 0,
        index: int = 0,
    ) -> "SWAVEntry":
        """Encodes standard 16-bit PCM WAV audio into an SWAV entry."""
        wav_info = ADPCMCodec.read_wav(wav_bytes)
        sample_rate = wav_info["sample_rate"]
        samples = wav_info["samples"]

        if wav_info["channels"] != 1:
            # Downmix stereo to mono if necessary
            mono_samples = []
            for i in range(0, len(samples), wav_info["channels"]):
                mono_samples.append(samples[i])
            samples = mono_samples

        timer_period = 0x0180  # Default timer period register

        if wave_type == 2:
            # IMA-ADPCM
            init_sample = samples[0] if samples else 0
            init_index = 0
            comp_bytes, _, _ = ADPCMCodec.encode_ima(
                samples, initial_predictor=init_sample, initial_index=init_index
            )
            preamble = struct.pack("<hbB", init_sample, init_index, 0)
            raw_payload = preamble + comp_bytes
        elif wave_type == 1:
            # PCM16
            raw_payload = bytearray()
            for s in samples:
                raw_payload.extend(struct.pack("<h", s))
            raw_payload = bytes(raw_payload)
        elif wave_type == 0:
            # PCM8
            raw_payload = bytearray()
            for s in samples:
                raw_payload.extend(struct.pack("<b", max(-128, min(127, s >> 8))))
            raw_payload = bytes(raw_payload)
        else:
            raise ValueError(f"Unsupported wave_type: {wave_type}")

        # Pad payload to 4-byte (32-bit word) boundary
        pad = (4 - (len(raw_payload) % 4)) % 4
        if pad > 0:
            raw_payload += b"\x00" * pad

        total_words = len(raw_payload) // 4
        if loop_flag:
            # Convert loop start from samples to words
            if wave_type == 2:
                loop_start_words = math.ceil(loop_start_samples / 8)  # 8 samples per word (4 bytes = 8 nibbles)
            elif wave_type == 1:
                loop_start_words = math.ceil(loop_start_samples / 2)  # 2 samples per word (4 bytes = 2 int16)
            else:
                loop_start_words = math.ceil(loop_start_samples / 4)  # 4 samples per word
            loop_start_words = min(total_words, max(0, loop_start_words))
            loop_len_words = total_words - loop_start_words
        else:
            loop_start_words = total_words
            loop_len_words = 0

        header_size = 12
        entry_size = header_size + len(raw_payload)

        return cls(
            index=index,
            offset=0,
            size=entry_size,
            wave_type=wave_type,
            loop_flag=loop_flag,
            sample_rate=sample_rate,
            timer_period=timer_period,
            loop_start_words=loop_start_words,
            loop_len_words=loop_len_words,
            payload=raw_payload,
        )

    def to_bytes(self) -> bytes:
        """Serializes the SWAV entry header and audio payload."""
        header = struct.pack(
            "<BBHHHI",
            self.wave_type,
            self.loop_flag,
            self.sample_rate,
            self.timer_period,
            self.loop_start_words,
            self.loop_len_words,
        )
        return header + self.payload


class SWARArchive:
    """
    Nintendo DS Nitro Sound Wave Archive (SWAR) parser, extractor, and rebuilder.
    Contains bank audio sample waveforms (SWAV) referenced by instrument banks (SBNK).
    """

    MAGIC = b"SWAR"

    def __init__(self, data: bytes) -> None:
        if len(data) < 64:
            raise ParseError("Data too small for SWAR header (minimum 64 bytes).")

        if data[:4] != self.MAGIC:
            raise ParseError(f"Invalid SWAR magic: {data[:4]!r}")

        self.data = bytearray(data)
        endian, version, self.file_size, self.header_size, num_blocks = struct.unpack_from("<HHIHH", self.data, 4)

        if endian != 0xFEFF:
            raise ParseError(f"Unsupported SWAR endianness: 0x{endian:04X} (expected 0xFEFF).")

        # Parse DATA block
        self.data_block_offset = self.header_size
        data_magic, self.data_block_size = struct.unpack_from("<4sI", self.data, self.data_block_offset)
        if data_magic != b"DATA":
            raise ParseError(f"Invalid DATA block magic: {data_magic!r}")

        # Table of SWAV offsets
        # Offset +40 in DATA block is num_swav
        self.num_swav = struct.unpack_from("<I", self.data, self.data_block_offset + 40)[0]
        offset_table_pos = self.data_block_offset + 44

        self.samples: List[Optional[SWAVEntry]] = []
        raw_offsets = []

        for i in range(self.num_swav):
            off = struct.unpack_from("<I", self.data, offset_table_pos + i * 4)[0]
            raw_offsets.append(off)

        # Parse each SWAV entry
        for i, off in enumerate(raw_offsets):
            if off == 0 or off >= len(self.data):
                self.samples.append(None)
                continue

            # Read 12-byte header
            wave_type, loop_flag, sample_rate, timer_period, loop_s, loop_len = struct.unpack_from(
                "<BBHHHI", self.data, off
            )

            # Calculate total sample words
            total_words = loop_s + loop_len
            payload_len = total_words * 4

            payload_start = off + 12
            payload_end = payload_start + payload_len

            if payload_end <= len(self.data):
                payload_data = bytes(self.data[payload_start:payload_end])
            else:
                payload_data = bytes(self.data[payload_start:])

            entry = SWAVEntry(
                index=i,
                offset=off,
                size=12 + len(payload_data),
                wave_type=wave_type,
                loop_flag=loop_flag,
                sample_rate=sample_rate,
                timer_period=timer_period,
                loop_start_words=loop_s,
                loop_len_words=loop_len,
                payload=payload_data,
            )
            self.samples.append(entry)

    @classmethod
    def from_file(cls, path: str) -> "SWARArchive":
        """Loads and parses an SWAR archive from disk."""
        with open(path, "rb") as f:
            return cls(f.read())

    def extract_all(self, output_dir: str) -> Dict[str, Any]:
        """
        Extracts all valid SWAV samples into .wav audio files and saves swar_manifest.json.
        """
        os.makedirs(output_dir, exist_ok=True)
        manifest_entries: List[Dict[str, Any]] = []
        extracted_count = 0

        for entry in self.samples:
            if entry is None:
                manifest_entries.append({"index": len(manifest_entries), "empty": True})
                continue

            fname = f"{entry.index:03d}.wav"
            out_path = os.path.join(output_dir, fname)
            entry.save_wav(out_path)
            extracted_count += 1

            manifest_entries.append(
                {
                    "index": entry.index,
                    "empty": False,
                    "relpath": fname,
                    "wave_type": entry.wave_type,
                    "loop_flag": entry.loop_flag,
                    "sample_rate": entry.sample_rate,
                    "timer_period": entry.timer_period,
                    "loop_start_words": entry.loop_start_words,
                    "loop_len_words": entry.loop_len_words,
                    "size": entry.size,
                }
            )

        manifest = {
            "total_slots": len(self.samples),
            "extracted_count": extracted_count,
            "samples": manifest_entries,
        }

        with open(os.path.join(output_dir, "swar_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return manifest

    def repack_from_dir(self, input_dir: str) -> int:
        """
        Scans input_dir for modified .wav files and updates corresponding SWAV entries.
        Returns count of replaced samples.
        """
        if not os.path.isdir(input_dir):
            raise FileNotFoundError(f"Input directory not found: '{input_dir}'")

        manifest_path = os.path.join(input_dir, "swar_manifest.json")
        meta_dict: Dict[int, Dict[str, Any]] = {}
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                raw_meta = json.load(f)
                for item in raw_meta.get("samples", []):
                    if not item.get("empty", False):
                        meta_dict[item["index"]] = item

        replaced = 0
        for fname in sorted(os.listdir(input_dir)):
            if not fname.endswith(".wav"):
                continue

            stem = os.path.splitext(fname)[0]
            if not stem.isdigit():
                continue

            idx = int(stem)
            if idx < 0 or idx >= len(self.samples):
                continue

            orig_entry = self.samples[idx]
            w_type = meta_dict.get(idx, {}).get("wave_type", orig_entry.wave_type if orig_entry else 2)
            l_flag = meta_dict.get(idx, {}).get("loop_flag", orig_entry.loop_flag if orig_entry else 0)
            l_words = meta_dict.get(idx, {}).get("loop_start_words", orig_entry.loop_start_words if orig_entry else 0)

            fpath = os.path.join(input_dir, fname)
            with open(fpath, "rb") as f:
                wav_data = f.read()

            new_entry = SWAVEntry.from_wav(
                wav_data,
                wave_type=w_type,
                loop_flag=l_flag,
                index=idx,
            )
            new_entry.loop_start_words = l_words
            new_entry.loop_len_words = (len(new_entry.payload) // 4) - l_words

            self.samples[idx] = new_entry
            replaced += 1

        return replaced

    def to_bytes(self) -> bytes:
        """
        Rebuilds the pristine binary SWAR container with all updated SWAV entries.
        """
        # DATA block header
        num_swav = len(self.samples)
        table_size = num_swav * 4
        base_data_header_len = 8 + 32 + 4 + table_size  # 44 + num_swav * 4

        # Align payload start to 32 bytes
        cur_file_pos = 16 + base_data_header_len
        pad_data = (32 - (cur_file_pos % 32)) % 32
        cur_file_pos += pad_data

        swav_payloads = bytearray()
        offset_table = bytearray()

        for i, entry in enumerate(self.samples):
            if entry is None:
                offset_table.extend(struct.pack("<I", 0))
            else:
                # Align each SWAV to 4 bytes
                align = (4 - (cur_file_pos % 4)) % 4
                if align > 0:
                    swav_payloads.extend(b"\x00" * align)
                    cur_file_pos += align

                offset_table.extend(struct.pack("<I", cur_file_pos))
                entry_bytes = entry.to_bytes()
                swav_payloads.extend(entry_bytes)
                cur_file_pos += len(entry_bytes)

        # Assemble DATA block
        data_block = bytearray(b"DATA")
        data_block_size = 8 + 32 + 4 + table_size + pad_data + len(swav_payloads)
        data_block.extend(struct.pack("<I", data_block_size))
        data_block.extend(b"\x00" * 32)  # 32 bytes reserved
        data_block.extend(struct.pack("<I", num_swav))
        data_block.extend(offset_table)
        if pad_data > 0:
            data_block.extend(b"\x00" * pad_data)
        data_block.extend(swav_payloads)

        # Assemble SWAR 16-byte Header
        total_file_size = 16 + len(data_block)
        header = bytearray(self.MAGIC)
        header.extend(struct.pack("<HHIHH", 0xFEFF, 0x0100, total_file_size, 16, 1))

        return bytes(header + data_block)
