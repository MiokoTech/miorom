"""
tests/test_platforms_wii_brlan.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii BRLAN (Binary Revolution Layout Animation) Engine.
Tests cover:
- Header and pai1 section binary serialization and parsing
- Mathematical curve evaluation: Step, Linear, and Hermite cubic splines
- Multi-pane animation synthetic creation and roundtrip serialization
- Keyframe mutation and timeline duration scaling
- Interoperability with BRLYT layout panes
- File disk I/O and diagnostics summary
"""

import os
import tempfile

import pytest

from miorom.platforms.wii import (
    BRLANFile,
    BRLANKeyframe,
    BRLANPaneAnim,
    BRLANTrack,
    BRLYTPaneStruct,
)
from miorom.platforms.wii.brlan import (
    BRLAN_MAGIC,
    CURVE_TYPE_HERMITE,
    CURVE_TYPE_LINEAR,
    CURVE_TYPE_STEP,
    PAI1_MAGIC,
    BRLANHeaderStruct,
    BRLANPai1HeaderStruct,
)


def test_brlan_header_and_pai1_structs():
    """Verify BRLAN and pai1 declarative binary structs."""
    hdr = BRLANHeaderStruct(
        magic=BRLAN_MAGIC,
        bom=0xFEFF,
        version=0x0008,
        file_size=0x100,
        header_size=16,
        section_count=1,
    )
    b_hdr = hdr.to_bytes()
    assert len(b_hdr) == 16
    assert b_hdr[:4] == b"RLAN"

    parsed_hdr = BRLANHeaderStruct.from_bytes(b_hdr, offset=0)
    assert parsed_hdr.bom == 0xFEFF
    assert parsed_hdr.version == 0x0008
    assert parsed_hdr.file_size == 0x100

    pai1 = BRLANPai1HeaderStruct(
        magic=PAI1_MAGIC,
        size=0xF0,
        frame_count=90,
        loop_flag=1,
        file_num=0,
        anim_tag_num=3,
        anim_tag_offset=0x14,
    )
    b_pai1 = pai1.to_bytes()
    assert len(b_pai1) == 0x14
    assert b_pai1[:4] == b"pai1"

    parsed_pai1 = BRLANPai1HeaderStruct.from_bytes(b_pai1, offset=0)
    assert parsed_pai1.frame_count == 90
    assert parsed_pai1.loop_flag == 1
    assert parsed_pai1.anim_tag_num == 3


def test_step_curve_interpolation():
    """Verify Step (constant) curve interpolation behavior."""
    track = BRLANTrack(
        property_id=10,  # alpha
        curve_type=CURVE_TYPE_STEP,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=0.0),
            BRLANKeyframe(frame=10.0, value=128.0),
            BRLANKeyframe(frame=20.0, value=255.0),
        ],
    )

    # Clamped before start
    assert track.evaluate(-5.0) == 0.0
    # Exactly at first keyframe
    assert track.evaluate(0.0) == 0.0
    # Between 0 and 10: stays at 0.0
    assert track.evaluate(5.0) == 0.0
    assert track.evaluate(9.99) == 0.0
    # Steps to 128.0 at frame 10.0
    assert track.evaluate(10.0) == 128.0
    assert track.evaluate(15.0) == 128.0
    # Steps to 255.0 at frame 20.0
    assert track.evaluate(20.0) == 255.0
    # Clamped after end
    assert track.evaluate(30.0) == 255.0


def test_linear_curve_interpolation():
    """Verify Linear curve interpolation accuracy and boundary clamping."""
    track = BRLANTrack(
        property_id=0,  # translate_x
        curve_type=CURVE_TYPE_LINEAR,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=100.0),
            BRLANKeyframe(frame=20.0, value=300.0),
        ],
    )

    # Clamping
    assert track.evaluate(-10.0) == 100.0
    assert track.evaluate(25.0) == 300.0

    # Start and End
    assert track.evaluate(0.0) == 100.0
    assert track.evaluate(20.0) == 300.0

    # Intermediate linear points
    assert pytest.approx(track.evaluate(10.0), rel=1e-5) == 200.0  # Midpoint
    assert pytest.approx(track.evaluate(5.0), rel=1e-5) == 150.0   # 25%
    assert pytest.approx(track.evaluate(15.0), rel=1e-5) == 250.0  # 75%


def test_hermite_cubic_spline_interpolation():
    """Verify Hermite cubic spline interpolation with smooth tangents."""
    # Flat tangents (ease-in, ease-out)
    track = BRLANTrack(
        property_id=6,  # scale_x
        curve_type=CURVE_TYPE_HERMITE,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=0.0, slope=0.0),
            BRLANKeyframe(frame=10.0, value=100.0, slope=0.0),
        ],
    )

    # Endpoints
    assert track.evaluate(0.0) == 0.0
    assert track.evaluate(10.0) == 100.0

    # Midpoint of symmetric Hermite spline with 0 slopes is exactly 50.0
    mid_val = track.evaluate(5.0)
    assert pytest.approx(mid_val, rel=1e-5) == 50.0

    # Quarter point (s = 0.25):
    # h00 = 2(1/64) - 3(1/16) + 1 = 2/64 - 12/64 + 64/64 = 54/64 = 0.84375
    # h01 = -2(1/64) + 3(1/16) = -2/64 + 12/64 = 10/64 = 0.15625
    # val = 0.84375 * 0 + 0.15625 * 100 = 15.625
    quarter_val = track.evaluate(2.5)
    assert pytest.approx(quarter_val, rel=1e-5) == 15.625


def test_synthetic_brlan_roundtrip_serialization():
    """Verify creating a multi-pane BRLAN, serializing to binary, and parsing back."""
    # Pane 1: P_Window
    pane_window = BRLANPaneAnim(name="P_Window", target_type="pan1")
    # Track 1: alpha (Linear 0 -> 255)
    t_alpha = BRLANTrack(
        property_id=10,
        curve_type=CURVE_TYPE_LINEAR,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=0.0),
            BRLANKeyframe(frame=30.0, value=255.0),
        ],
    )
    # Track 2: scale_x (Hermite 0.5 -> 1.0)
    t_scale_x = BRLANTrack(
        property_id=6,
        curve_type=CURVE_TYPE_HERMITE,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=0.5, slope=0.0),
            BRLANKeyframe(frame=30.0, value=1.0, slope=0.0),
        ],
    )
    pane_window.set_track(t_alpha)
    pane_window.set_track(t_scale_x)

    # Pane 2: P_Icon
    pane_icon = BRLANPaneAnim(name="P_Icon", target_type="pic1")
    # Track: translate_y (Step)
    t_pos_y = BRLANTrack(
        property_id=1,
        curve_type=CURVE_TYPE_STEP,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=50.0),
            BRLANKeyframe(frame=15.0, value=100.0),
            BRLANKeyframe(frame=30.0, value=150.0),
        ],
    )
    pane_icon.set_track(t_pos_y)

    anim = BRLANFile(
        frame_count=60,
        loop=True,
        panes={"P_Window": pane_window, "P_Icon": pane_icon},
    )

    # Serialize to bytes
    raw_bytes = anim.to_bytes()
    assert len(raw_bytes) > 0x40
    assert raw_bytes[:4] == b"RLAN"
    assert raw_bytes[16:20] == b"pai1"

    # Parse back
    loaded_anim = BRLANFile.from_bytes(raw_bytes)
    assert loaded_anim.frame_count == 60
    assert loaded_anim.loop is True
    assert len(loaded_anim.panes) == 2
    assert "P_Window" in loaded_anim.panes
    assert "P_Icon" in loaded_anim.panes

    # Verify evaluated values match at key frames
    eval_orig = anim.evaluate(15.0)
    eval_loaded = loaded_anim.evaluate(15.0)

    assert pytest.approx(eval_orig["P_Window"]["alpha"], rel=1e-5) == 127.5
    assert pytest.approx(eval_loaded["P_Window"]["alpha"], rel=1e-5) == 127.5
    assert eval_orig["P_Icon"]["translate_y"] == 100.0
    assert eval_loaded["P_Icon"]["translate_y"] == 100.0


def test_keyframe_mutation_and_duration_scaling():
    """Verify adding/modifying keyframes and timeline scaling."""
    pane = BRLANPaneAnim(name="P_Dialog", target_type="pan1")
    track = BRLANTrack(
        property_id=10,  # alpha
        curve_type=CURVE_TYPE_LINEAR,
        keyframes=[
            BRLANKeyframe(frame=0.0, value=0.0),
            BRLANKeyframe(frame=60.0, value=255.0),
        ],
    )
    pane.set_track(track)
    anim = BRLANFile(frame_count=60, loop=False, panes={"P_Dialog": pane})

    # Add midpoint keyframe
    track.set_keyframe(frame=30.0, value=180.0)
    assert len(track.keyframes) == 3
    assert track.evaluate(30.0) == 180.0

    # Scale duration by 0.5 (double speed: 60 frames -> 30 frames)
    anim.scale_duration(0.5)
    assert anim.frame_count == 30
    assert track.keyframes[0].frame == 0.0
    assert track.keyframes[1].frame == 15.0
    assert track.keyframes[1].value == 180.0
    assert track.keyframes[2].frame == 30.0
    assert track.keyframes[2].value == 255.0

    # Verify evaluation at frame 15.0 now produces 180.0
    assert anim.evaluate(15.0)["P_Dialog"]["alpha"] == 180.0


def test_brlyt_interoperability():
    """Verify applying BRLAN animation evaluated state directly to BRLYT layout panes."""
    pane = BRLYTPaneStruct(
        name="P_Window",
        x=0.0,
        y=0.0,
        alpha=0,
    )

    anim_pane = BRLANPaneAnim(name="P_Window")
    t_pos_x = BRLANTrack(
        property_id=0,
        curve_type=CURVE_TYPE_LINEAR,
        keyframes=[BRLANKeyframe(0.0, 10.0), BRLANKeyframe(20.0, 50.0)],
    )
    t_alpha = BRLANTrack(
        property_id=10,
        curve_type=CURVE_TYPE_LINEAR,
        keyframes=[BRLANKeyframe(0.0, 50.0), BRLANKeyframe(20.0, 255.0)],
    )
    anim_pane.set_track(t_pos_x)
    anim_pane.set_track(t_alpha)

    # Evaluate at frame 10.0
    state = anim_pane.evaluate(10.0)
    assert pytest.approx(state["translate_x"], rel=1e-5) == 30.0
    assert pytest.approx(state["alpha"], rel=1e-5) == 152.5

    # Apply to BRLYT pane
    pane.x = state["translate_x"]
    pane.alpha = int(state["alpha"])

    assert pane.x == 30.0
    assert pane.alpha == 152


def test_brlan_disk_io_and_summary():
    """Verify saving to disk, loading from file, and summary diagnostic string."""
    pane = BRLANPaneAnim(name="P_Test", target_type="pan1")
    t = BRLANTrack(property_id=8, curve_type=CURVE_TYPE_STEP, keyframes=[BRLANKeyframe(0.0, 640.0)])
    pane.set_track(t)
    anim = BRLANFile(frame_count=45, loop=True, panes={"P_Test": pane})

    summary = anim.summary()
    assert "BRLAN Animation" in summary
    assert "P_Test" in summary
    assert "width" in summary

    with tempfile.TemporaryDirectory() as tmpdir:
        brlan_path = os.path.join(tmpdir, "anim.brlan")
        anim.save(brlan_path)
        assert os.path.exists(brlan_path)
        assert os.path.getsize(brlan_path) > 0

        loaded = BRLANFile.from_file(brlan_path)
        assert loaded.frame_count == 45
        assert loaded.loop is True
        assert "P_Test" in loaded.panes
        assert loaded.panes["P_Test"].tracks["width"].evaluate(10.0) == 640.0
