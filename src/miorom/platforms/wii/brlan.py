"""
miorom.platforms.wii.brlan
~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii BRLAN (Binary Revolution Layout Animation) Engine.

Pure-Python, builder, and timeline curve evaluator
for Nintendo NW4R layout animation files (.brlan), which accompany BRLYT (.brlyt)
UI layouts across modern Wii titles (e.g. Mario Kart Wii, Super Smash Bros. Brawl,
New Super Mario Bros. Wii, The Legend of Zelda: Skyward Sword).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from miorom.core import schema
from miorom.core.schema import (
    U8,
    U16,
    U32,
    BinaryStruct,
    FixedString,
    Float32,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.result import MioRomResult

BRLAN_MAGIC = b"RLAN"
PAI1_MAGIC = b"pai1"

# Curve Interpolation Types
CURVE_TYPE_STEP = 0
CURVE_TYPE_LINEAR = 1
CURVE_TYPE_HERMITE = 2

# Target Property IDs
PROPERTY_MAP_ID_TO_NAME: Dict[int, str] = {
    0: "translate_x",
    1: "translate_y",
    2: "translate_z",
    3: "rotate_x",
    4: "rotate_y",
    5: "rotate_z",
    6: "scale_x",
    7: "scale_y",
    8: "width",
    9: "height",
    10: "alpha",
    11: "mat_color_r",
    12: "mat_color_g",
    13: "mat_color_b",
    14: "mat_color_a",
    15: "uv_translate_x",
    16: "uv_translate_y",
    17: "uv_scale_x",
    18: "uv_scale_y",
}

PROPERTY_MAP_NAME_TO_ID: Dict[str, int] = {v: k for k, v in PROPERTY_MAP_ID_TO_NAME.items()}

class BRLANHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4, default=b"RLAN")
    bom = U16(default=0xFEFF)
    version = U16(default=0x0008)
    file_size = U32(default=0)
    header_size = U16(default=16)
    section_count = U16(default=1)


class BRLANPai1HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4, default=b"pai1")
    size = U32(default=0)
    frame_count = U16(default=0)
    loop_flag = U8(default=1)
    pad = U8(default=0)
    file_num = U16(default=0)
    anim_tag_num = U16(default=0)
    anim_tag_offset = U32(default=0x14)


class BRLANTargetHeaderStruct(BinaryStruct):
    _endian = ">"
    name = FixedString(20, default="")
    target_type = FixedString(4, default="pan1")
    num_curves = U8(default=0)
    pad = RawBytes(3, default=b"\x00\x00\x00")


class BRLANTrackHeaderStruct(BinaryStruct):
    _endian = ">"
    target_property = U8(default=0)
    curve_type = U8(default=1)  # Linear by default
    key_count = U16(default=0)
    keys_offset = U32(default=8)


class BRLANKeyframeLinearStruct(BinaryStruct):
    _endian = ">"
    frame = Float32(default=0.0)
    value = Float32(default=0.0)


class BRLANKeyframeHermiteStruct(BinaryStruct):
    _endian = ">"
    frame = Float32(default=0.0)
    value = Float32(default=0.0)
    slope = Float32(default=0.0)


@dataclass
class BRLANKeyframe(MioRomResult):
    """Represents a single animation keyframe point on a timeline."""
    frame: float
    value: float
    slope: float = 0.0


class BRLANTrack(MioRomResult):
    """
    Animates a single numerical property of a pane or material over time.
    Supports Step (constant), Linear, and Hermite cubic spline interpolation.
    """

    def __init__(
        self,
        property_id: int,
        curve_type: int = CURVE_TYPE_LINEAR,
        keyframes: Optional[List[BRLANKeyframe]] = None,
        property_name: Optional[str] = None,
    ):
        self.property_id = property_id
        self.curve_type = curve_type
        self.keyframes = sorted(keyframes or [], key=lambda k: k.frame)
        self.property_name = property_name or PROPERTY_MAP_ID_TO_NAME.get(property_id, f"prop_{property_id}")

    def evaluate(self, frame: float) -> float:
        """
        Mathematically evaluates the curve value at arbitrary floating-point frame `frame`.
        Handles boundary clamping and interpolation (Step, Linear, or Hermite spline).
        """
        if not self.keyframes:
            return 0.0
        if len(self.keyframes) == 1:
            return self.keyframes[0].value

        # Clamping before start or after end
        if frame <= self.keyframes[0].frame:
            return self.keyframes[0].value
        if frame >= self.keyframes[-1].frame:
            return self.keyframes[-1].value

        # Step (constant)
        if self.curve_type == CURVE_TYPE_STEP:
            val = self.keyframes[0].value
            for k in self.keyframes:
                if k.frame <= frame:
                    val = k.value
                else:
                    break
            return val

        # Locate interval [k0, k1] where k0.frame <= frame <= k1.frame
        k0 = self.keyframes[0]
        k1 = self.keyframes[1]
        for i in range(len(self.keyframes) - 1):
            if self.keyframes[i].frame <= frame <= self.keyframes[i + 1].frame:
                k0 = self.keyframes[i]
                k1 = self.keyframes[i + 1]
                break

        delta_t = k1.frame - k0.frame
        if delta_t <= 0.0:
            return k0.value

        # Linear
        if self.curve_type == CURVE_TYPE_LINEAR:
            alpha = (frame - k0.frame) / delta_t
            return k0.value + alpha * (k1.value - k0.value)

        # Hermite Cubic Spline
        if self.curve_type == CURVE_TYPE_HERMITE:
            s = (frame - k0.frame) / delta_t
            s2 = s * s
            s3 = s2 * s

            h00 = 2.0 * s3 - 3.0 * s2 + 1.0
            h10 = s3 - 2.0 * s2 + s
            h01 = -2.0 * s3 + 3.0 * s2
            h11 = s3 - s2

            val = (
                h00 * k0.value
                + h10 * delta_t * k0.slope
                + h01 * k1.value
                + h11 * delta_t * k1.slope
            )
            return val

        # Fallback to linear
        alpha = (frame - k0.frame) / delta_t
        return k0.value + alpha * (k1.value - k0.value)

    def set_keyframe(self, frame: float, value: float, slope: float = 0.0) -> None:
        """Sets or updates a keyframe at the given frame index."""
        for k in self.keyframes:
            if abs(k.frame - frame) < 1e-4:
                k.value = value
                k.slope = slope
                return
        self.keyframes.append(BRLANKeyframe(frame=frame, value=value, slope=slope))
        self.keyframes.sort(key=lambda k: k.frame)

    def remove_keyframe(self, frame: float) -> bool:
        """Removes a keyframe at the specified frame if present."""
        for i, k in enumerate(self.keyframes):
            if abs(k.frame - frame) < 1e-4:
                self.keyframes.pop(i)
                return True
        return False


class BRLANPaneAnim(MioRomResult):
    """Represents all animation curve tracks associated with a specific BRLYT layout pane or material."""

    def __init__(
        self,
        name: str,
        target_type: str = "pan1",
        tracks: Optional[Dict[str, BRLANTrack]] = None,
    ):
        self.name = name
        self.target_type = target_type
        self.tracks: Dict[str, BRLANTrack] = dict(tracks) if tracks else {}

    def evaluate(self, frame: float) -> Dict[str, float]:
        """Evaluates all active animation property tracks at the given frame."""
        res: Dict[str, float] = {}
        for prop_name, track in self.tracks.items():
            res[prop_name] = track.evaluate(frame)
        return res

    def get_track(self, property_name: str) -> Optional[BRLANTrack]:
        """Retrieves a track by property name (e.g. 'alpha', 'translate_x')."""
        return self.tracks.get(property_name)

    def set_track(self, track: BRLANTrack) -> None:
        """Sets or replaces a property track."""
        self.tracks[track.property_name] = track


class BRLANFile(MioRomResult):
    """
    Nintendo Wii BRLAN (Binary Revolution Layout Animation) container.
    Parses, evaluates, modifies, and rebuilds binary .brlan animation archives.
    """

    def __init__(
        self,
        frame_count: int = 60,
        loop: bool = True,
        panes: Optional[Dict[str, BRLANPaneAnim]] = None,
    ):
        self.frame_count = frame_count
        self.loop = loop
        self.panes: Dict[str, BRLANPaneAnim] = dict(panes) if panes else {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "BRLANFile":
        """Parses a raw binary BRLAN file buffer into an in-memory BRLANFile object."""
        if len(data) < BRLANHeaderStruct.sizeof():
            raise ParseError(f"Buffer too small for BRLAN header ({len(data)} < 16).")

        header = BRLANHeaderStruct.from_bytes(data, offset=0)
        if header.magic != BRLAN_MAGIC:
            raise ParseError(f"Invalid BRLAN magic: {header.magic!r} (expected b'RLAN').")

        # Find pai1 section
        pai1_off = header.header_size
        if pai1_off + BRLANPai1HeaderStruct.sizeof() > len(data):
            raise ParseError("BRLAN data missing pai1 section.")

        pai1 = BRLANPai1HeaderStruct.from_bytes(data, offset=pai1_off)
        if pai1.magic != PAI1_MAGIC:
            raise ParseError(f"Invalid section magic: {pai1.magic!r} (expected b'pai1').")

        frame_count = pai1.frame_count
        loop = pai1.loop_flag != 0
        num_targets = pai1.anim_tag_num
        tag_table_off = pai1_off + pai1.anim_tag_offset

        panes: Dict[str, BRLANPaneAnim] = {}

        for t_idx in range(num_targets):
            t_ptr_off = tag_table_off + t_idx * 4
            if t_ptr_off + 4 > len(data):
                break
            rel_target_off = schema.unpack_from(">I", data, t_ptr_off)[0]
            abs_target_off = pai1_off + rel_target_off

            if abs_target_off + BRLANTargetHeaderStruct.sizeof() > len(data):
                break

            target_hdr = BRLANTargetHeaderStruct.from_bytes(data, offset=abs_target_off)
            t_name = target_hdr.name.strip("\x00")
            t_type = target_hdr.target_type.strip("\x00")
            num_curves = target_hdr.num_curves

            tracks: Dict[str, BRLANTrack] = {}
            curve_ptrs_off = abs_target_off + BRLANTargetHeaderStruct.sizeof()

            for c_idx in range(num_curves):
                c_ptr_off = curve_ptrs_off + c_idx * 4
                if c_ptr_off + 4 > len(data):
                    break
                rel_curve_off = schema.unpack_from(">I", data, c_ptr_off)[0]
                abs_curve_off = abs_target_off + rel_curve_off

                if abs_curve_off + BRLANTrackHeaderStruct.sizeof() > len(data):
                    break

                track_hdr = BRLANTrackHeaderStruct.from_bytes(data, offset=abs_curve_off)
                prop_id = track_hdr.target_property
                curve_type = track_hdr.curve_type
                key_count = track_hdr.key_count
                abs_keys_off = abs_curve_off + track_hdr.keys_offset

                keyframes: List[BRLANKeyframe] = []

                if curve_type == CURVE_TYPE_HERMITE:
                    stride = BRLANKeyframeHermiteStruct.sizeof()
                    for k_idx in range(key_count):
                        k_off = abs_keys_off + k_idx * stride
                        if k_off + stride > len(data):
                            break
                        kst = BRLANKeyframeHermiteStruct.from_bytes(data, offset=k_off)
                        keyframes.append(BRLANKeyframe(frame=kst.frame, value=kst.value, slope=kst.slope))
                else:
                    stride = BRLANKeyframeLinearStruct.sizeof()
                    for k_idx in range(key_count):
                        k_off = abs_keys_off + k_idx * stride
                        if k_off + stride > len(data):
                            break
                        kst = BRLANKeyframeLinearStruct.from_bytes(data, offset=k_off)
                        keyframes.append(BRLANKeyframe(frame=kst.frame, value=kst.value, slope=0.0))

                track = BRLANTrack(
                    property_id=prop_id,
                    curve_type=curve_type,
                    keyframes=keyframes,
                )
                tracks[track.property_name] = track

            pane_anim = BRLANPaneAnim(name=t_name, target_type=t_type, tracks=tracks)
            panes[t_name] = pane_anim

        return cls(frame_count=frame_count, loop=loop, panes=panes)

    @classmethod
    def from_file(cls, path: str) -> "BRLANFile":
        """Loads and parses a BRLAN file directly from disk."""
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        """Serializes this BRLAN animation container into a valid binary .brlan buffer."""

        num_targets = len(self.panes)
        tag_table_size = num_targets * 4
        base_target_data_offset = 0x14 + tag_table_size
        while base_target_data_offset % 4 != 0:
            base_target_data_offset += 1

        target_offsets: List[int] = []
        body_data = bytearray()

        for _, pane in sorted(self.panes.items(), key=lambda item: item[0]):
            rel_target_start = base_target_data_offset + len(body_data)
            target_offsets.append(rel_target_start)

            num_curves = len(pane.tracks)
            curve_ptrs_placeholder_len = num_curves * 4
            target_hdr_size = BRLANTargetHeaderStruct.sizeof()
            target_header_block_size = target_hdr_size + curve_ptrs_placeholder_len
            while target_header_block_size % 4 != 0:
                target_header_block_size += 1

            # Build curves for this target
            curve_offsets: List[int] = []
            curves_body = bytearray()

            for _, track in sorted(pane.tracks.items(), key=lambda item: item[1].property_id):
                rel_curve_start = target_header_block_size + len(curves_body)
                curve_offsets.append(rel_curve_start)

                keys_header_size = BRLANTrackHeaderStruct.sizeof()
                # Keyframes array
                keys_data = bytearray()
                if track.curve_type == CURVE_TYPE_HERMITE:
                    for k in track.keyframes:
                        keys_data.extend(
                            BRLANKeyframeHermiteStruct(
                                frame=float(k.frame),
                                value=float(k.value),
                                slope=float(k.slope),
                            ).to_bytes()
                        )
                else:
                    for k in track.keyframes:
                        keys_data.extend(
                            BRLANKeyframeLinearStruct(
                                frame=float(k.frame),
                                value=float(k.value),
                            ).to_bytes()
                        )

                # Write Track Header
                track_st = BRLANTrackHeaderStruct(
                    target_property=track.property_id,
                    curve_type=track.curve_type,
                    key_count=len(track.keyframes),
                    keys_offset=keys_header_size,
                )
                curves_body.extend(track_st.to_bytes())
                curves_body.extend(keys_data)
                while len(curves_body) % 4 != 0:
                    curves_body.append(0)

            # Write Target Header
            target_st = BRLANTargetHeaderStruct(
                name=pane.name,
                target_type=pane.target_type,
                num_curves=num_curves,
            )
            body_data.extend(target_st.to_bytes())
            # Write curve pointer table
            for c_ptr in curve_offsets:
                body_data.extend(schema.pack(">I", c_ptr))
            while len(body_data) % 4 != 0:
                body_data.append(0)

            body_data.extend(curves_body)
            while len(body_data) % 4 != 0:
                body_data.append(0)

        # Assemble pai1 section
        pai1_bytes = bytearray()
        total_pai1_size = 0x14 + tag_table_size + len(body_data)
        # 16-byte align pai1 section
        while total_pai1_size % 16 != 0:
            total_pai1_size += 1

        pai1_hdr = BRLANPai1HeaderStruct(
            magic=PAI1_MAGIC,
            size=total_pai1_size,
            frame_count=self.frame_count,
            loop_flag=1 if self.loop else 0,
            file_num=0,
            anim_tag_num=num_targets,
            anim_tag_offset=0x14,
        )
        pai1_bytes.extend(pai1_hdr.to_bytes())

        # Write target offset table
        for t_off in target_offsets:
            pai1_bytes.extend(schema.pack(">I", t_off))

        # Pad to base_target_data_offset
        while len(pai1_bytes) < base_target_data_offset:
            pai1_bytes.append(0)

        pai1_bytes.extend(body_data)
        while len(pai1_bytes) < total_pai1_size:
            pai1_bytes.append(0)

        # Prepend file header
        total_file_size = 16 + len(pai1_bytes)
        file_hdr = BRLANHeaderStruct(
            magic=BRLAN_MAGIC,
            bom=0xFEFF,
            version=0x0008,
            file_size=total_file_size,
            header_size=16,
            section_count=1,
        )

        return file_hdr.to_bytes() + bytes(pai1_bytes)

    def save(self, path: str) -> None:
        """Saves this animation to disk as a binary .brlan file."""
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def evaluate(self, frame: float) -> Dict[str, Dict[str, float]]:
        """
        Evaluates the animation state of all panes and materials at frame `frame`.
        Returns mapping of: {pane_name: {property_name: interpolated_float_value}}
        """
        res: Dict[str, Dict[str, float]] = {}
        for name, pane in self.panes.items():
            res[name] = pane.evaluate(frame)
        return res

    def scale_duration(self, factor: float) -> None:
        """
        Scales the entire animation timeline duration by `factor` (e.g. 0.5 to double speed, 2.0 to halve speed).
        Adjusts total frame_count and all keyframe timestamps.
        """
        if factor <= 0.0:
            raise ValueError(f"Scaling factor must be positive, got {factor}.")

        self.frame_count = max(1, int(round(self.frame_count * factor)))
        for pane in self.panes.values():
            for track in pane.tracks.values():
                for k in track.keyframes:
                    k.frame = k.frame * factor
                    if track.curve_type == CURVE_TYPE_HERMITE:
                        k.slope = k.slope / factor

    def summary(self) -> str:
        """Returns human-readable diagnostic overview of the animation structure."""
        lines = [
            f"BRLAN Animation (duration: {self.frame_count} frames, loop: {self.loop})",
            f"Animated Targets: {len(self.panes)}",
        ]
        for name, pane in sorted(self.panes.items()):
            lines.append(f"  - Target '{name}' [{pane.target_type}]: {len(pane.tracks)} tracks")
            for prop, track in sorted(pane.tracks.items()):
                ctype_name = (
                    "Step" if track.curve_type == CURVE_TYPE_STEP
                    else "Linear" if track.curve_type == CURVE_TYPE_LINEAR
                    else "Hermite"
                )
                lines.append(f"      * {prop}: {len(track.keyframes)} keys ({ctype_name})")
        return "\n".join(lines)
