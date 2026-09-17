"""
tests/test_text_msbf.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit test suite for Nintendo MSBF (Message Studio Binary Flow) Dialogue Flowchart Engine.
Tests low-level binary structures, FLW3 node pool and branch table serialization,
FEN1 entry points hash table, FOP1 choice options, MSBT cross-linking, and Mermaid generation.
"""

import pytest

from miorom.errors import ParseError
from miorom.text.msbf import (
    ChoiceNode,
    EventNode,
    MessageNode,
    MSBFFile,
    MSBFHeaderStruct,
    create_synthetic_msbf,
)
from miorom.text.msbt import MSBTEntry, MSBTFile


def _create_sample_dialogue_nodes():
    """Helper to create a standard 5-node branching shopkeeper conversation graph."""
    # Node 0: Message "Welcome!" -> Next is Node 1
    # Node 1: Choice "Buy" (-> Node 2) or "Leave" (-> Node 3)
    # Node 2: Event 101 (Give item) -> Next is Node 4
    # Node 3: Message "See you later!" -> End
    # Node 4: Message "Thank you for buying!" -> End
    return [
        MessageNode(node_id=0, message_index=0, next_node_id=1),
        ChoiceNode(node_id=1, options=["Buy Potion", "Leave"], branch_targets=[2, 3]),
        EventNode(node_id=2, event_id=101, param=5, next_node_id=4),
        MessageNode(node_id=3, message_index=1, next_node_id=None),
        MessageNode(node_id=4, message_index=2, next_node_id=None),
    ]


def test_msbf_synthetic_creation_and_parse():
    """Verifies creating a synthetic MSBF flow file and parsing sections, nodes, and entries."""
    nodes = _create_sample_dialogue_nodes()
    entries = {"Talk_Merchant": 0}

    raw_msbf = create_synthetic_msbf(nodes=nodes, entries=entries, encoding="utf-16", endian=">")
    assert raw_msbf[:8] == b"MsgFlwBn"

    msbf = MSBFFile.from_bytes(raw_msbf)
    assert len(msbf.nodes) == 5
    assert msbf.entries == {"Talk_Merchant": 0}
    assert msbf.endian == ">"

    # Check node 0
    n0 = msbf.nodes[0]
    assert isinstance(n0, MessageNode)
    assert n0.message_index == 0
    assert n0.next_node_id == 1

    # Check node 1 (Choice)
    n1 = msbf.nodes[1]
    assert isinstance(n1, ChoiceNode)
    assert len(n1.branch_targets) == 2
    assert n1.branch_targets == [2, 3]
    assert "Buy Potion" in n1.options
    assert "Leave" in n1.options

    # Check node 2 (Event)
    n2 = msbf.nodes[2]
    assert isinstance(n2, EventNode)
    assert n2.event_id == 101
    assert n2.param == 5
    assert n2.next_node_id == 4


def test_msbf_roundtrip_serialization():
    """Verifies parsing a binary MSBF file and serializing back with exact node preservation."""
    nodes = _create_sample_dialogue_nodes()
    entries = {"Talk_Merchant": 0}

    raw_msbf = create_synthetic_msbf(nodes=nodes, entries=entries, encoding="utf-16", endian=">")
    msbf = MSBFFile.from_bytes(raw_msbf)

    # Repack
    repacked = msbf.to_bytes()
    re_msbf = MSBFFile.from_bytes(repacked)

    assert len(re_msbf.nodes) == 5
    assert re_msbf.entries == {"Talk_Merchant": 0}
    assert re_msbf.nodes[1].branch_targets == [2, 3]
    assert re_msbf.nodes[2].event_id == 101
    assert re_msbf.nodes[4].message_index == 2


def test_msbf_branch_and_choice_navigation():
    """Verifies ChoiceNode with 3 distinct branch options and targets."""
    nodes = [
        MessageNode(node_id=0, message_index=0, next_node_id=1),
        ChoiceNode(node_id=1, options=["Option A", "Option B", "Option C"], branch_targets=[2, 3, 4]),
        MessageNode(node_id=2, message_index=1, next_node_id=None),
        MessageNode(node_id=3, message_index=2, next_node_id=None),
        MessageNode(node_id=4, message_index=3, next_node_id=None),
    ]
    raw = create_synthetic_msbf(nodes=nodes, entries={"ThreeChoices": 0})
    msbf = MSBFFile.from_bytes(raw)

    c_node = msbf.nodes[1]
    assert isinstance(c_node, ChoiceNode)
    assert len(c_node.options) == 3
    assert c_node.branch_targets == [2, 3, 4]


def test_msbf_msbt_linking():
    """Verifies bidirectional linking of MSBF message nodes with an MSBTFile."""
    nodes = _create_sample_dialogue_nodes()
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, entries={"Talk_Merchant": 0})

    msbt = MSBTFile(
        entries=[
            MSBTEntry(label="Shop_Welcome", text="Welcome to the shop!"),
            MSBTEntry(label="Shop_Bye", text="Come again soon!"),
            MSBTEntry(label="Shop_Thanks", text="Here is your item!"),
        ]
    )

    msbf.link_msbt(msbt)

    # Check node 0 linked
    n0 = msbf.nodes[0]
    assert isinstance(n0, MessageNode)
    assert n0.msbt_label == "Shop_Welcome"
    assert n0.text_preview == "Welcome to the shop!"

    # Check node 3 linked
    n3 = msbf.nodes[3]
    assert isinstance(n3, MessageNode)
    assert n3.msbt_label == "Shop_Bye"
    assert n3.text_preview == "Come again soon!"

    # Check node 4 linked
    n4 = msbf.nodes[4]
    assert isinstance(n4, MessageNode)
    assert n4.msbt_label == "Shop_Thanks"
    assert n4.text_preview == "Here is your item!"


def test_msbf_mermaid_flowchart_generation():
    """Verifies Markdown Mermaid flowchart generation for story and choice visualization."""
    nodes = _create_sample_dialogue_nodes()
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, entries={"Talk_Merchant": 0})

    msbt = MSBTFile(
        entries=[
            MSBTEntry(label="Shop_Welcome", text="Welcome to the shop!"),
            MSBTEntry(label="Shop_Bye", text="Come again soon!"),
            MSBTEntry(label="Shop_Thanks", text="Here is your item!"),
        ]
    )
    msbf.link_msbt(msbt)

    mermaid_code = msbf.to_mermaid()
    assert mermaid_code.startswith("flowchart TD")
    assert "Entry_Talk_Merchant" in mermaid_code
    assert 'Node_1{"Choice Point"}' in mermaid_code
    assert 'Node_1 -- "Buy Potion" --> Node_2' in mermaid_code
    assert 'Node_1 -- "Leave" --> Node_3' in mermaid_code
    assert "Shop_Welcome" in mermaid_code


def test_msbf_json_dict_roundtrip():
    """Verifies dictionary serialization and deserialization (JSON tool interoperability)."""
    nodes = _create_sample_dialogue_nodes()
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, entries={"Talk_Merchant": 0})

    data_dict = msbf.to_dict()
    assert data_dict["entries"] == {"Talk_Merchant": 0}
    assert len(data_dict["nodes"]) == 5

    re_msbf = MSBFFile.from_dict(data_dict)
    assert len(re_msbf.nodes) == 5
    assert re_msbf.nodes[1].branch_targets == [2, 3]
    assert re_msbf.to_bytes() == msbf.to_bytes()


def test_msbf_error_handling():
    """Verifies robust error detection for truncated data and invalid container magic."""
    # Truncated header
    with pytest.raises(ParseError, match="Data too short for MSBF header"):
        MSBFFile.from_bytes(b"MsgFlwBn" * 2)

    # Bad magic
    bad_header = MSBFHeaderStruct(magic=b"BADMAGIC").to_bytes()
    with pytest.raises(ParseError, match="Invalid MSBF magic"):
        MSBFFile.from_bytes(bad_header)


def test_msbf_big_endian_wii_binary_headers_and_nodes():
    """Verifies that big-endian Wii MSBF writes and reads structs in true big-endian order."""
    import struct

    nodes = _create_sample_dialogue_nodes()
    entries = {"Talk_Merchant": 0}
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, entries=entries, encoding="utf-16", endian=">")
    raw = msbf.to_bytes()

    # 1. Root header: file_size should be in big-endian at offset 18 (2 bytes BOM + 2 pad + 1 enc + 1 ver + 2 sec_count + 2 pad = 10, offset 18 is file_size)
    assert raw[:8] == b"MsgFlwBn"
    assert raw[8:10] == b"\xFE\xFF"

    # 2. FLW3 section header starts at offset 32: magic b"FLW3", size (4 bytes BE)
    assert raw[32:36] == b"FLW3"
    flw_sec_size = struct.unpack(">I", raw[36:40])[0]
    flw_sec_size_le = struct.unpack("<I", raw[36:40])[0]
    # Size must be reasonable (e.g. ~100-200 bytes), NOT millions of bytes due to LE byte-swap
    assert flw_sec_size < 1000
    assert flw_sec_size_le > 10000

    # 3. FLW3 header starts at offset 48: node_count (2B BE), branch_count (2B BE)
    node_count_be = struct.unpack(">H", raw[48:50])[0]
    assert node_count_be == 5

    # 4. First node starts at offset 56: node_type should be 1 (NODE_TYPE_MESSAGE) in BE (0x0001)
    assert raw[56:58] == b"\x00\x01"

    # 5. Full parse round-trip
    parsed = MSBFFile.from_bytes(raw)
    assert len(parsed.nodes) == 5
    assert parsed.endian == ">"
    assert isinstance(parsed.nodes[0], MessageNode)
    assert parsed.nodes[0].message_index == 0
    assert parsed.nodes[0].next_node_id == 1
    assert isinstance(parsed.nodes[1], ChoiceNode)
    assert parsed.nodes[1].branch_targets == [2, 3]
    assert isinstance(parsed.nodes[2], EventNode)
    assert parsed.nodes[2].event_id == 101
    assert parsed.entries == {"Talk_Merchant": 0}


def test_msbf_little_endian_3ds_roundtrip():
    """Verifies that little-endian (3DS / Switch) MSBF works correctly."""
    nodes = _create_sample_dialogue_nodes()
    entries = {"Start": 0}
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, entries=entries, encoding="utf-8", endian="<")
    raw = msbf.to_bytes()

    assert raw[8:10] == b"\xFF\xFE"
    parsed = MSBFFile.from_bytes(raw)
    assert len(parsed.nodes) == 5
    assert parsed.endian == "<"
    assert isinstance(parsed.nodes[0], MessageNode)
    assert parsed.entries == {"Start": 0}


def test_msbf_utf8_big_endian_roundtrip():
    """Verifies that UTF-8 encoding on Big-Endian MSBF archives roundtrips option strings without corruption."""
    nodes = [
        MessageNode(node_id=0, message_index=0, next_node_id=1),
        ChoiceNode(node_id=1, options=["Accept Quest", "Decline"], branch_targets=[2, 3]),
        MessageNode(node_id=2, message_index=1, next_node_id=None),
        MessageNode(node_id=3, message_index=2, next_node_id=None),
    ]
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, encoding="utf-8", endian=">")
    raw = msbf.to_bytes()
    assert raw[8:10] == b"\xFE\xFF"

    loaded = MSBFFile.from_bytes(raw)
    assert loaded.encoding == "utf-8"
    assert loaded.endian == ">"
    choice_node = loaded.nodes[1]
    assert isinstance(choice_node, ChoiceNode)
    assert choice_node.options == ["Accept Quest", "Decline"]


def test_msbf_multiple_choice_nodes_distinct_options():
    """Verifies that multiple ChoiceNodes in a flow tree maintain distinct options without crosstalk."""
    nodes = [
        MessageNode(node_id=0, message_index=0, next_node_id=1),
        ChoiceNode(node_id=1, options=["Buy Potion", "Leave"], branch_targets=[2, 3]),
        MessageNode(node_id=2, message_index=1, next_node_id=4),
        MessageNode(node_id=3, message_index=2, next_node_id=None),
        ChoiceNode(node_id=4, options=["Fight Dragon", "Run Away", "Cast Spell"], branch_targets=[5, 6, 7]),
        MessageNode(node_id=5, message_index=3, next_node_id=None),
        MessageNode(node_id=6, message_index=4, next_node_id=None),
        MessageNode(node_id=7, message_index=5, next_node_id=None),
    ]
    msbf = MSBFFile(nodes={n.node_id: n for n in nodes}, encoding="utf-16", endian=">")
    raw = msbf.to_bytes()

    loaded = MSBFFile.from_bytes(raw)
    assert len(loaded.nodes) == 8
    choice1 = loaded.nodes[1]
    choice2 = loaded.nodes[4]
    assert isinstance(choice1, ChoiceNode)
    assert isinstance(choice2, ChoiceNode)
    assert choice1.options == ["Buy Potion", "Leave"]
    assert choice2.options == ["Fight Dragon", "Run Away", "Cast Spell"]


