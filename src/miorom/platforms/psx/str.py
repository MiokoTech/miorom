from miorom.result import MioRomResult
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.audio.xa import CdXaDecoder, cdxa_to_wav
from miorom.core.schema import BinaryStruct, U16, U32


@dataclass
class CdSector(MioRomResult):
    index: int
    file_num: int
    channel: int
    submode: int
    coding: int
    is_audio: bool
    is_video: bool
    payload: bytes


@dataclass
class StrFrameChunk(MioRomResult):
    magic: int
    channel_id: int
    chunk_index: int
    chunk_count: int
    frame_index: int
    bytes_used: int
    width: int
    height: int
    data: bytes


@dataclass
class StrFrame(MioRomResult):
    frame_index: int
    width: int
    height: int
    chunks_found: int
    chunks_total: int
    bs_data: bytes

    @property
    def is_complete(self) -> bool:
        return self.chunks_found >= self.chunks_total

class STRVideoChunkHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = U16()
    channel_id = U16()
    chunk_index = U16()
    chunk_count = U16()
    frame_index = U32()
    bytes_used = U32()
    width = U16()
    height = U16()


class StrDemuxer:
    """
    PlayStation 1 (.str) Movie Stream demuxer.
    Parses CD-ROM raw 2352-byte / 2048-byte sector streams, separates interleaved
    CD-XA audio sectors and MDEC video frame chunks, and reconstructs full video frames.
    """

    def __init__(self, data: bytes):
        self.raw_data = data
        self.sector_size = self._detect_sector_size(data)
        self.sectors: List[CdSector] = []
        self._parse_sectors()

    @staticmethod
    def _detect_sector_size(data: bytes) -> int:
        if len(data) >= 2352 and data[:12] == b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00":
            return 2352
        if len(data) >= 2336:
            # Check if second sector is at 2336
            return 2336
        return 2048

    def _parse_sectors(self):
        self.sectors.clear()
        total_len = len(self.raw_data)
        num_sectors = total_len // self.sector_size

        for idx in range(num_sectors):
            sec_start = idx * self.sector_size
            sec_bytes = self.raw_data[sec_start:sec_start + self.sector_size]

            if self.sector_size == 2352:
                # Subheader at 0x10..0x18
                file_num = sec_bytes[0x10]
                channel = sec_bytes[0x11]
                submode = sec_bytes[0x12]
                coding = sec_bytes[0x13]
                payload = sec_bytes[0x18:0x18 + 2304]
            elif self.sector_size == 2336:
                file_num = sec_bytes[0]
                channel = sec_bytes[1]
                submode = sec_bytes[2]
                coding = sec_bytes[3]
                payload = sec_bytes[8:8 + 2304]
            else:
                # 2048 raw data
                file_num = 0
                channel = 0
                submode = 0
                coding = 0
                payload = sec_bytes[:2048]

            # In CD-ROM XA submode:
            # Bit 2 (0x04) = Audio sector
            # Bit 1 (0x02) = Video sector
            # Or standard submode flags: 0x40 = Audio, 0x20 = Video
            is_audio = bool(submode & 0x04) or bool(submode & 0x40)
            is_video = bool(submode & 0x02) or bool(submode & 0x20)

            # Fallback heuristic if submode is 0 (raw sectors)
            if not is_audio and not is_video and len(payload) >= 2:
                magic = U16().unpack(payload, 0, "<")[0]
                if magic in (0x0160, 0x0150):
                    is_video = True

            self.sectors.append(
                CdSector(
                    index=idx,
                    file_num=file_num,
                    channel=channel,
                    submode=submode,
                    coding=coding,
                    is_audio=is_audio,
                    is_video=is_video,
                    payload=payload,
                )
            )

    def get_audio_sectors(self, channel: Optional[int] = None) -> List[CdSector]:
        """Filter audio sectors, optionally by channel ID."""
        return [
            s for s in self.sectors
            if s.is_audio and (channel is None or s.channel == channel)
        ]

    def demux_audio(
        self,
        channel: Optional[int] = None,
        sample_rate: int = 37800,
        stereo: bool = True,
    ) -> bytes:
        """Demux all audio sectors matching channel and export to WAV format."""
        audio_sec = self.get_audio_sectors(channel)
        if not audio_sec:
            return b""
        payloads = [s.payload for s in audio_sec]
        return cdxa_to_wav(payloads, sample_rate=sample_rate, stereo=stereo)

    def demux_video_frames(self) -> List[StrFrame]:
        """Demux and reconstruct complete video frames from STR video sectors."""
        frames_chunks: Dict[int, List[StrFrameChunk]] = {}

        for sec in self.sectors:
            if not sec.is_video or len(sec.payload) < 32:
                continue

            chunk_header = STRVideoChunkHeaderStruct.from_bytes(sec.payload)
            magic = chunk_header.magic
            channel_id = chunk_header.channel_id
            chunk_idx = chunk_header.chunk_index
            chunk_count = chunk_header.chunk_count
            frame_idx = chunk_header.frame_index
            bytes_used = chunk_header.bytes_used
            width = chunk_header.width
            height = chunk_header.height

            # STR chunk magic 0x0160 (v2/v3) or 0x0150 (v1)
            if magic not in (0x0160, 0x0150):
                continue

            chunk_payload = sec.payload[32:32 + 2016]
            chunk = StrFrameChunk(
                magic=magic,
                channel_id=channel_id,
                chunk_index=chunk_idx,
                chunk_count=chunk_count,
                frame_index=frame_idx,
                bytes_used=bytes_used,
                width=width,
                height=height,
                data=chunk_payload,
            )

            if frame_idx not in frames_chunks:
                frames_chunks[frame_idx] = []
            frames_chunks[frame_idx].append(chunk)

        # Assemble frames
        result_frames: List[StrFrame] = []
        for frame_idx in sorted(frames_chunks.keys()):
            chunks = frames_chunks[frame_idx]
            chunks.sort(key=lambda c: c.chunk_index)

            first = chunks[0]
            total_expected = first.chunk_count
            bytes_needed = first.bytes_used

            all_data = bytearray()
            for ch in chunks:
                all_data.extend(ch.data)

            trimmed_data = bytes(all_data[:bytes_needed]) if bytes_needed > 0 else bytes(all_data)

            result_frames.append(
                StrFrame(
                    frame_index=frame_idx,
                    width=first.width,
                    height=first.height,
                    chunks_found=len(chunks),
                    chunks_total=total_expected,
                    bs_data=trimmed_data,
                )
            )

        return result_frames
