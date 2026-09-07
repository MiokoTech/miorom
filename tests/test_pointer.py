import struct
from miorom.core.pointer import PointerTable, PointerEntry


def test_pointer_table_read_and_relocate():
    # Construct a dummy pointer table with base 0x1000
    # Entry 0: rel 0x100 (abs 0x1100), flag 0xFFFF
    # Entry 1: rel 0x200 (abs 0x1200), flag 0xFFFF
    data = struct.pack(">IIII", 0x100, 0xFFFF, 0x200, 0xFFFF)

    table = PointerTable.read_from(
        data=data,
        table_offset=0,
        count=2,
        base_offset=0x1000,
        stride=8,
        has_flags=True,
        endian=">"
    )

    assert len(table) == 2
    assert table[0].absolute_target == 0x1100
    assert table[1].absolute_target == 0x1200

    # Relocate abs 0x1100 to 0x1150
    table.relocate({0x1100: 0x1150})
    assert table[0].absolute_target == 0x1150
    assert table[0].target_offset == 0x150

    rebuilt = table.build_bytes()
    expected = struct.pack(">IIII", 0x150, 0xFFFF, 0x200, 0xFFFF)
    assert rebuilt == expected
