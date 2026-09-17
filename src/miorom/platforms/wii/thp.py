"""
miorom.platforms.wii.thp
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo GameCube & Wii THP Video Cutscene Engine.

Pure-Python, zero-dependency parser, demuxer, muxer, audio dubbing, and hardsubbing engine
for Nintendo official THP video containers (.thp, magic b"THP\\x00").
Used throughout GameCube and Wii titles (e.g., Super Smash Bros. Brawl Subspace Emissary,
Super Mario Galaxy 1 & 2 cutscenes, The Legend of Zelda: Twilight Princess, Mario Kart Wii).

Features:
- Pure-Python, zero external dependencies (no ffmpeg, no opencv, no numpy, no C extensions).
- Strict declarative binary primitives via miorom.core.schema (BinaryStruct).
- Motion JPEG video frame extraction and individual frame image replacement (hardsubbing).
- Interleaved multi-channel DSP-ADPCM audio demuxing to standard continuous 16-bit PCM WavSound.
- Zero-drift cutscene audio dubbing replacement with fractional sample allocation.
- Bi-directional movie rebuilding with automatic frame linkage and max buffer recalculation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

from miorom.audio.dsp_adpcm import DEFAULT_DSP_COEFFS, DSPADPCMCodec
from miorom.audio.wav_codec import WavCodec, WavSound
from miorom.core.schema import (
    I16,
    U32,
    BinaryStruct,
    Float32,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.platforms.wii.brstm import encode_dsp_adpcm_channel

# ==============================================================================
# Constants & Magics
# ==============================================================================

THP_MAGIC = b"THP\x00"
THP_VERSION_11 = 0x00011000

COMPONENT_TYPE_VIDEO = 0
COMPONENT_TYPE_AUDIO = 1
COMPONENT_TYPE_NONE = 0xFF

VIDEO_FORMAT_YUV420 = 0
VIDEO_FORMAT_YUV422 = 1


# ==============================================================================
# Declarative Binary Struct Definitions (Low-Level Primitives via schema)
# ==============================================================================

class THPHeaderStruct(BinaryStruct):
    """
    Root 0x30-byte header of a Nintendo GameCube / Wii .thp video container.
    """
    _endian = ">"
    magic = RawBytes(4, default=THP_MAGIC)
    version = U32(default=THP_VERSION_11)
    max_buffer_size = U32(default=0)
    max_audio_samples = U32(default=0)
    fps = Float32(default=29.97)
    num_frames = U32(default=0)
    first_frame_offset = U32(default=0)
    component_data_offset = U32(default=0x30)
    first_frame_size = U32(default=0)
    last_frame_offset = U32(default=0)
    _reserved = RawBytes(8, default=b"\x00" * 8)


class THPComponentHeaderStruct(BinaryStruct):
    """
    Descriptor table of components contained within the THP video stream.
    """
    _endian = ">"
    num_components = U32(default=2)
    component_types = RawBytes(16, default=b"\x00\x01" + b"\xff" * 14)


class THPVideoInfoStruct(BinaryStruct):
    """
    Video format specification (dimensions and color format).
    """
    _endian = ">"
    width = U32(default=640)
    height = U32(default=480)
    video_format = U32(default=VIDEO_FORMAT_YUV420)


class THPAudioInfoStruct(BinaryStruct):
    """
    Audio stream parameters (channels, sample rate, total samples, and tracks).
    """
    _endian = ">"
    channels = U32(default=1)
    sample_rate = U32(default=32000)
    num_samples = U32(default=0)
    track_count = U32(default=1)


class THPFrameHeaderStruct(BinaryStruct):
    """
    16-byte header prepending every interleaved frame slice.
    """
    _endian = ">"
    next_frame_size = U32(default=0)
    prev_frame_size = U32(default=0)
    image_size = U32(default=0)
    audio_size = U32(default=0)


class THPAudioFrameHeaderStruct(BinaryStruct):
    """
    DSP-ADPCM channel header for an individual mono frame's audio slice (44 bytes).
    """
    _endian = ">"
    channel_size = U32(default=0)
    num_samples = U32(default=0)
    coefs = RawBytes(32, default=b"\x00" * 32)
    prev1 = I16(default=0)
    prev2 = I16(default=0)


class THPStereoAudioFrameHeaderStruct(BinaryStruct):
    """
    DSP-ADPCM stereo header for an individual frame's audio slice (80 bytes / 0x50).
    Used by authentic Nintendo GameCube & Wii stereo cutscenes.
    """
    _endian = ">"
    channel_size = U32(default=0)
    num_samples = U32(default=0)
    coefs1 = RawBytes(32, default=b"\x00" * 32)
    coefs2 = RawBytes(32, default=b"\x00" * 32)
    prev1_ch1 = I16(default=0)
    prev2_ch1 = I16(default=0)
    prev1_ch2 = I16(default=0)
    prev2_ch2 = I16(default=0)


# ==============================================================================
# Analytical Data Models
# ==============================================================================

@dataclass
class THPFrame:
    """
    Represents an individual video/audio slice in a THP cutscene.
    """
    index: int
    image_data: bytes           # Raw Motion JPEG bitstream (starts with 0xFF 0xD8)
    audio_data: bytes = b""     # Raw interleaved DSP-ADPCM audio slice
    num_audio_samples: int = 0  # Number of audio samples in this frame

    def get_image_bytes(self) -> bytes:
        """Returns the raw JPEG bitstream for this frame."""
        return self.image_data

    def set_image_bytes(self, new_jpeg: bytes) -> None:
        """Replaces the image data of this frame (e.g. for hardsubbing)."""
        if not new_jpeg.startswith(b"\xff\xd8"):
            raise ParseError("Image data does not appear to be a valid JPEG bitstream (missing 0xFF 0xD8 header)")
        self.image_data = new_jpeg


# ==============================================================================
# High-Level THP Movie Engine
# ==============================================================================

class THPMovie:
    """
    Nintendo GameCube & Wii THP Movie Engine.
    Represents an in-memory parsed .thp cutscene with full demuxing, frame extraction,
    drift-free audio dubbing, and bit-exact muxing.
    """

    def __init__(
        self,
        fps: float = 29.97,
        width: int = 640,
        height: int = 480,
        video_format: int = VIDEO_FORMAT_YUV420,
        has_audio: bool = True,
        audio_channels: int = 1,
        audio_sample_rate: int = 32000,
    ):
        self.fps = fps
        self.width = width
        self.height = height
        self.video_format = video_format
        self.has_audio = has_audio
        self.audio_channels = audio_channels
        self.audio_sample_rate = audio_sample_rate
        self.frames: List[THPFrame] = []

    @classmethod
    def from_bytes(cls, data: bytes) -> THPMovie:
        """
        Parses a .thp movie from raw binary bytes.
        """
        if len(data) < THPHeaderStruct.sizeof():
            raise ParseError(f"Data too short for THP header ({len(data)} < {THPHeaderStruct.sizeof()} bytes)")

        header = THPHeaderStruct.from_bytes(data, offset=0)
        if header.magic != THP_MAGIC:
            raise ParseError(f"Invalid THP magic: {header.magic!r} (expected {THP_MAGIC!r})")

        # Parse Component Data
        comp_off = header.component_data_offset
        if comp_off + THPComponentHeaderStruct.sizeof() > len(data):
            raise ParseError("Component header offset exceeds file size")

        comp_hdr = THPComponentHeaderStruct.from_bytes(data, offset=comp_off)

        # Parse Video Info
        vid_off = comp_off + THPComponentHeaderStruct.sizeof()
        if vid_off + THPVideoInfoStruct.sizeof() > len(data):
            raise ParseError("Video component descriptor exceeds file size")
        vid_info = THPVideoInfoStruct.from_bytes(data, offset=vid_off)

        # Parse Audio Info if present
        has_audio = False
        aud_channels = 1
        aud_sample_rate = 32000
        types_array = list(comp_hdr.component_types)
        if COMPONENT_TYPE_AUDIO in types_array[:comp_hdr.num_components]:
            has_audio = True
            aud_off = vid_off + THPVideoInfoStruct.sizeof()
            if aud_off + THPAudioInfoStruct.sizeof() <= len(data):
                aud_info = THPAudioInfoStruct.from_bytes(data, offset=aud_off)
                aud_channels = aud_info.channels
                aud_sample_rate = aud_info.sample_rate

        movie = cls(
            fps=header.fps,
            width=vid_info.width,
            height=vid_info.height,
            video_format=vid_info.video_format,
            has_audio=has_audio,
            audio_channels=aud_channels,
            audio_sample_rate=aud_sample_rate,
        )

        # Parse Sequential Frame Slices
        cur_offset = header.first_frame_offset
        for i in range(header.num_frames):
            if cur_offset + THPFrameHeaderStruct.sizeof() > len(data):
                break

            f_hdr = THPFrameHeaderStruct.from_bytes(data, offset=cur_offset)
            payload_start = cur_offset + THPFrameHeaderStruct.sizeof()

            # Image slice
            img_data = data[payload_start : payload_start + f_hdr.image_size]

            # Audio slice
            aud_data = b""
            num_samples = 0
            if f_hdr.audio_size > 0:
                aud_start = payload_start + f_hdr.image_size
                aud_data = data[aud_start : aud_start + f_hdr.audio_size]
                if len(aud_data) >= THPAudioFrameHeaderStruct.sizeof():
                    aud_f_hdr = THPAudioFrameHeaderStruct.from_bytes(aud_data, offset=0)
                    num_samples = aud_f_hdr.num_samples

            movie.frames.append(
                THPFrame(
                    index=i,
                    image_data=img_data,
                    audio_data=aud_data,
                    num_audio_samples=num_samples,
                )
            )

            # Move to next frame
            if f_hdr.next_frame_size > 0:
                cur_offset += THPFrameHeaderStruct.sizeof() + f_hdr.image_size + f_hdr.audio_size
            else:
                break

        return movie

    @classmethod
    def from_file(cls, filepath: Union[str, os.PathLike]) -> THPMovie:
        """
        Loads and parses a .thp movie from disk.
        """
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    @property
    def num_frames(self) -> int:
        """Total number of video frames."""
        return len(self.frames)

    @property
    def duration_seconds(self) -> float:
        """Total playback duration in seconds."""
        if self.fps <= 0:
            return 0.0
        return self.num_frames / self.fps

    def get_frame(self, index: int) -> THPFrame:
        """
        Retrieves a frame by its zero-based index.
        """
        if index < 0 or index >= len(self.frames):
            raise IndexError(f"Frame index {index} out of range (0..{len(self.frames) - 1})")
        return self.frames[index]

    def replace_frame(self, index: int, new_jpeg_bytes: bytes) -> None:
        """
        Replaces the video image of a specific frame (e.g. for hardsubbing).
        """
        frame = self.get_frame(index)
        frame.set_image_bytes(new_jpeg_bytes)

    def export_frames(self, output_dir: Union[str, os.PathLike], prefix: str = "frame_") -> List[str]:
        """
        Exports all frames as individual JPEG image files.
        """
        os.makedirs(output_dir, exist_ok=True)
        written_paths: List[str] = []
        for f in self.frames:
            filename = f"{prefix}{f.index:05d}.jpg"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as out:
                out.write(f.image_data)
            written_paths.append(filepath)
        return written_paths

    def export_audio_wav(self) -> WavSound:
        """
        Demuxes all interleaved DSP-ADPCM audio slices across frames into a continuous WavSound.
        Supports both Mono (44-byte slice header) and Stereo (80-byte slice header).
        """
        if not self.has_audio or not self.frames:
            raise ValueError("THP movie does not have an audio track")

        channels = max(1, min(2, self.audio_channels))

        if channels == 1:
            master_samples: List[int] = []

            for frame in self.frames:
                if not frame.audio_data or len(frame.audio_data) < THPAudioFrameHeaderStruct.sizeof():
                    continue

                aud_hdr = THPAudioFrameHeaderStruct.from_bytes(frame.audio_data, offset=0)
                # Unpack 16 coefficients from coefs raw bytes
                coefs = [
                    int.from_bytes(aud_hdr.coefs[i * 2 : i * 2 + 2], "big", signed=True)
                    for i in range(16)
                ]
                if len(coefs) < 16 or all(c == 0 for c in coefs):
                    coefs = list(DEFAULT_DSP_COEFFS)

                raw_adpcm = frame.audio_data[THPAudioFrameHeaderStruct.sizeof() : THPAudioFrameHeaderStruct.sizeof() + aud_hdr.channel_size]
                decoded = DSPADPCMCodec.decode(raw_adpcm, coefs=coefs)

                if aud_hdr.num_samples > 0:
                    decoded = decoded[:aud_hdr.num_samples]
                master_samples.extend(decoded)

            return WavSound(
                samples=master_samples,
                sample_rate=self.audio_sample_rate,
                channels=1,
                bits_per_sample=16,
            )
        else:
            # Stereo (2 channels)
            left_master: List[int] = []
            right_master: List[int] = []

            for frame in self.frames:
                if not frame.audio_data:
                    continue

                if len(frame.audio_data) >= THPStereoAudioFrameHeaderStruct.sizeof():
                    aud_hdr = THPStereoAudioFrameHeaderStruct.from_bytes(frame.audio_data, offset=0)
                    ch_sz = aud_hdr.channel_size
                    num_s = aud_hdr.num_samples

                    coefs1 = [
                        int.from_bytes(aud_hdr.coefs1[k * 2 : k * 2 + 2], "big", signed=True)
                        for k in range(16)
                    ]
                    if all(c == 0 for c in coefs1):
                        coefs1 = list(DEFAULT_DSP_COEFFS)

                    coefs2 = [
                        int.from_bytes(aud_hdr.coefs2[k * 2 : k * 2 + 2], "big", signed=True)
                        for k in range(16)
                    ]
                    if all(c == 0 for c in coefs2):
                        coefs2 = list(DEFAULT_DSP_COEFFS)

                    hdr_sz = THPStereoAudioFrameHeaderStruct.sizeof()
                    ch1_data = frame.audio_data[hdr_sz : hdr_sz + ch_sz]
                    ch2_data = frame.audio_data[hdr_sz + ch_sz : hdr_sz + 2 * ch_sz]

                    decoded1 = DSPADPCMCodec.decode(ch1_data, coefs=coefs1)
                    decoded2 = DSPADPCMCodec.decode(ch2_data, coefs=coefs2)

                    if num_s > 0:
                        decoded1 = decoded1[:num_s]
                        decoded2 = decoded2[:num_s]

                    min_len = min(len(decoded1), len(decoded2))
                    left_master.extend(decoded1[:min_len])
                    right_master.extend(decoded2[:min_len])

            # Interleave left and right
            interleaved: List[int] = []
            total = min(len(left_master), len(right_master))
            for i in range(total):
                interleaved.append(left_master[i])
                interleaved.append(right_master[i])

            return WavSound(
                samples=interleaved,
                sample_rate=self.audio_sample_rate,
                channels=2,
                bits_per_sample=16,
            )

    def set_audio_wav(self, wav_input: Union[WavSound, bytes, str, os.PathLike]) -> None:
        """
        Replaces the movie's audio track with a new WAV audio file or WavSound.
        Supports both Mono and Stereo tracks with high-precision fractional sample allocation across frames.
        """
        if isinstance(wav_input, (str, os.PathLike)):
            with open(wav_input, "rb") as f:
                wav_sound = WavCodec.decode(f.read())
        elif isinstance(wav_input, bytes):
            wav_sound = WavCodec.decode(wav_input)
        elif isinstance(wav_input, WavSound):
            wav_sound = wav_input
        else:
            raise TypeError(f"Invalid WAV input type: {type(wav_input)}")

        channels = max(1, min(2, wav_sound.channels))
        srate = wav_sound.sample_rate

        self.has_audio = True
        self.audio_channels = channels
        self.audio_sample_rate = srate

        total_frames = len(self.frames)
        if total_frames == 0:
            return

        coefs = list(DEFAULT_DSP_COEFFS)
        coef_bytes = bytearray()
        for c in coefs:
            coef_bytes.extend(c.to_bytes(2, "big", signed=True))

        if channels == 1:
            mono_wav = wav_sound.to_mono() if wav_sound.channels > 1 else wav_sound
            all_samples = mono_wav.samples

            # Interleave audio slices across frames using fractional accumulator
            for i, frame in enumerate(self.frames):
                start_sample = round(i * srate / self.fps)
                end_sample = round((i + 1) * srate / self.fps)
                slice_samples = all_samples[start_sample:end_sample] if start_sample < len(all_samples) else []

                if slice_samples:
                    adpcm_bytes, _, s1, s2 = encode_dsp_adpcm_channel(slice_samples, coefs=coefs)

                    aud_f_hdr = THPAudioFrameHeaderStruct(
                        channel_size=len(adpcm_bytes),
                        num_samples=len(slice_samples),
                        coefs=bytes(coef_bytes),
                        prev1=s1,
                        prev2=s2,
                    )
                    frame.audio_data = aud_f_hdr.to_bytes() + adpcm_bytes
                    frame.num_audio_samples = len(slice_samples)
                else:
                    frame.audio_data = b""
                    frame.num_audio_samples = 0
        else:
            # Stereo (2 channels)
            left_samples = [wav_sound.samples[k] for k in range(0, len(wav_sound.samples), 2)]
            right_samples = [wav_sound.samples[k + 1] for k in range(0, len(wav_sound.samples) - 1, 2)]

            for i, frame in enumerate(self.frames):
                start_sample = round(i * srate / self.fps)
                end_sample = round((i + 1) * srate / self.fps)
                slice_left = left_samples[start_sample:end_sample] if start_sample < len(left_samples) else []
                slice_right = right_samples[start_sample:end_sample] if start_sample < len(right_samples) else []

                if slice_left and slice_right:
                    adpcm_left, _, s1_l, s2_l = encode_dsp_adpcm_channel(slice_left, coefs=coefs)
                    adpcm_right, _, s1_r, s2_r = encode_dsp_adpcm_channel(slice_right, coefs=coefs)

                    num_s = min(len(slice_left), len(slice_right))
                    ch_sz = max(len(adpcm_left), len(adpcm_right))
                    if len(adpcm_left) < ch_sz:
                        adpcm_left = adpcm_left.ljust(ch_sz, b"\x00")
                    if len(adpcm_right) < ch_sz:
                        adpcm_right = adpcm_right.ljust(ch_sz, b"\x00")

                    aud_hdr = THPStereoAudioFrameHeaderStruct(
                        channel_size=ch_sz,
                        num_samples=num_s,
                        coefs1=bytes(coef_bytes),
                        coefs2=bytes(coef_bytes),
                        prev1_ch1=s1_l,
                        prev2_ch1=s2_l,
                        prev1_ch2=s1_r,
                        prev2_ch2=s2_r,
                    )
                    frame.audio_data = aud_hdr.to_bytes() + adpcm_left + adpcm_right
                    frame.num_audio_samples = num_s
                else:
                    frame.audio_data = b""
                    frame.num_audio_samples = 0

    def to_bytes(self) -> bytes:
        """
        Muxes and serializes the entire THP movie into a bit-exact binary stream.
        Automatically updates frame linkage sizes, buffer bounds, and section offsets.
        """
        # 1. Build Component Data
        comp_types = bytearray([COMPONENT_TYPE_VIDEO])
        num_components = 1
        if self.has_audio:
            comp_types.append(COMPONENT_TYPE_AUDIO)
            num_components = 2
        while len(comp_types) < 16:
            comp_types.append(COMPONENT_TYPE_NONE)

        comp_hdr = THPComponentHeaderStruct(
            num_components=num_components,
            component_types=bytes(comp_types),
        )

        vid_info = THPVideoInfoStruct(
            width=self.width,
            height=self.height,
            video_format=self.video_format,
        )

        total_audio_samples = sum(f.num_audio_samples for f in self.frames)
        aud_info = THPAudioInfoStruct(
            channels=self.audio_channels,
            sample_rate=self.audio_sample_rate,
            num_samples=total_audio_samples,
            track_count=1,
        )

        comp_data = comp_hdr.to_bytes() + vid_info.to_bytes()
        if self.has_audio:
            comp_data += aud_info.to_bytes()

        # Component data offset is 0x30 immediately following root header
        comp_data_offset = 0x30
        first_frame_offset = comp_data_offset + len(comp_data)

        # Pad component data to 16-byte alignment
        pad_len = (16 - (first_frame_offset % 16)) % 16
        comp_data += b"\x00" * pad_len
        first_frame_offset += pad_len

        # 2. Build Frames and calculate linkage
        num_frames = len(self.frames)
        frame_sizes: List[int] = []

        # Pre-compute frame sizes (header + image + audio)
        for f in self.frames:
            sz = THPFrameHeaderStruct.sizeof() + len(f.image_data) + len(f.audio_data)
            frame_sizes.append(sz)

        max_buf_size = 0
        max_audio_samps = 0
        cur_offset = first_frame_offset
        last_frame_offset = cur_offset

        frames_blob = bytearray()

        for i, f in enumerate(self.frames):
            last_frame_offset = cur_offset
            next_sz = frame_sizes[i + 1] if i + 1 < num_frames else 0
            prev_sz = frame_sizes[i - 1] if i > 0 else 0

            f_hdr = THPFrameHeaderStruct(
                next_frame_size=next_sz,
                prev_frame_size=prev_sz,
                image_size=len(f.image_data),
                audio_size=len(f.audio_data),
            )
            frame_slice = f_hdr.to_bytes() + f.image_data + f.audio_data
            frames_blob.extend(frame_slice)

            buf_size = THPFrameHeaderStruct.sizeof() + len(f.image_data) + len(f.audio_data)
            if buf_size > max_buf_size:
                max_buf_size = buf_size
            if f.num_audio_samples > max_audio_samps:
                max_audio_samps = f.num_audio_samples

            cur_offset += len(frame_slice)

        first_frame_sz = frame_sizes[0] if frame_sizes else 0

        # 3. Build Root Header
        root_hdr = THPHeaderStruct(
            magic=THP_MAGIC,
            version=THP_VERSION_11,
            max_buffer_size=max_buf_size,
            max_audio_samples=max_audio_samps,
            fps=self.fps,
            num_frames=num_frames,
            first_frame_offset=first_frame_offset,
            component_data_offset=comp_data_offset,
            first_frame_size=first_frame_sz,
            last_frame_offset=last_frame_offset,
        )

        return root_hdr.to_bytes() + comp_data + bytes(frames_blob)

    def save(self, filepath: Union[str, os.PathLike]) -> None:
        """
        Saves the repacked THP movie to disk.
        """
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())

    def summary(self) -> str:
        """
        Returns a concise diagnostic string representation of the movie.
        """
        return (
            f"THP Movie: {self.width}x{self.height} @ {self.fps:.2f} fps | "
            f"{self.num_frames} frames ({self.duration_seconds:.2f}s) | "
            f"Audio: {'Yes (' + str(self.audio_sample_rate) + ' Hz, ' + str(self.audio_channels) + ' ch)' if self.has_audio else 'None'}"
        )


# ==============================================================================
# Factory / Helper Functions
# ==============================================================================

def create_synthetic_thp(
    width: int,
    height: int,
    fps: float,
    frames_jpegs: Sequence[bytes],
    audio_samples: Optional[List[int]] = None,
    sample_rate: int = 32000,
    channels: int = 1,
) -> bytes:
    """
    Scaffolding utility to create a valid synthetic .thp movie for testing.

    Args:
        width: Video frame width in pixels.
        height: Video frame height in pixels.
        fps: Frames per second.
        frames_jpegs: Sequence of raw JPEG image byte buffers.
        audio_samples: Optional PCM audio samples to interleave across frames.
        sample_rate: Audio sample rate in Hz.
        channels: Audio channels count (1 for mono, 2 for stereo).

    Returns:
        Raw binary bytes of the created .thp container.
    """
    has_audio = audio_samples is not None and len(audio_samples) > 0
    movie = THPMovie(
        fps=fps,
        width=width,
        height=height,
        video_format=VIDEO_FORMAT_YUV420,
        has_audio=has_audio,
        audio_channels=channels,
        audio_sample_rate=sample_rate,
    )

    for i, jpeg in enumerate(frames_jpegs):
        movie.frames.append(
            THPFrame(
                index=i,
                image_data=jpeg,
                audio_data=b"",
                num_audio_samples=0,
            )
        )

    if has_audio and audio_samples is not None:
        wav = WavSound(samples=audio_samples, sample_rate=sample_rate, channels=channels)
        movie.set_audio_wav(wav)

    return movie.to_bytes()
