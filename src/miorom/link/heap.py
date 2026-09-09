"""
from miorom.errors import ParseError
miorom.link.heap
~~~~~~~~~~~~~~~~
Dynamic In-ROM Runtime Heap Allocator (miorom_heap).
Provides slab and buddy memory management primitives and C/assembly runtime payload
generators to inject dynamic `malloc` and `free` routines into ROMs (DOL/ELF/GBA/NDS).
"""

from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


HEAP_MAGIC = 0x4D494F48  # 'MIOH' (MioHeap)
BLOCK_HEADER_SIZE = 16   # 16-byte header aligned
ALIGNMENT = 16


@dataclass
class HeapStats(MioRomResult):
    total_size: int
    used_bytes: int
    free_bytes: int
    num_allocations: int
    largest_free_block: int
    fragmentation_ratio: float


@dataclass
class MemBlock(MioRomResult):
    offset: int         # Offset relative to heap start
    size: int           # Usable payload size
    is_allocated: bool  # True if in use
    prev_offset: int = 0
    next_offset: int = 0


class MioRomHeap:
    """
    Dynamic In-ROM Heap Allocator Engine.
    Simulates runtime memory allocation, checks memory integrity,
    and generates C/assembly injection payloads for target architectures.
    """

    def __init__(self, base_ram: int = 0x80500000, total_size: int = 0x100000):
        if total_size < 0x1000:
            raise ParseError("Heap total size must be at least 4KB (0x1000 bytes)")

        self.base_ram = base_ram
        self.total_size = total_size
        self.buffer = bytearray(total_size)
        self.blocks: List[MemBlock] = []

        # Initialize first large free block
        initial_usable = total_size - BLOCK_HEADER_SIZE
        first_block = MemBlock(
            offset=0,
            size=initial_usable,
            is_allocated=False,
            prev_offset=0,
            next_offset=0,
        )
        self.blocks.append(first_block)
        self._write_block_header(first_block)

    def _align(self, size: int) -> int:
        return (size + (ALIGNMENT - 1)) & ~(ALIGNMENT - 1)

    def _write_block_header(self, block: MemBlock):
        # Header layout (16 bytes):
        # [0x00:0x04] Magic 'MIOH' (0x4D494F48)
        # [0x04:0x08] Usable Size (U32)
        # [0x08:0x0C] Flags (1 = allocated, 0 = free)
        # [0x0C:0x10] Next Block Offset (U32)
        flags = 1 if block.is_allocated else 0
        struct.pack_into(
            ">IIII",
            self.buffer,
            block.offset,
            HEAP_MAGIC,
            block.size,
            flags,
            block.next_offset,
        )

    def malloc(self, size: int) -> int:
        """
        Allocate a memory block of `size` bytes.
        Returns the absolute RAM address of the allocated payload.
        """
        if size <= 0:
            raise ParseError("Allocation size must be greater than 0")

        needed = self._align(size)
        chosen_idx = None

        for idx, block in enumerate(self.blocks):
            if not block.is_allocated and block.size >= needed:
                chosen_idx = idx
                break

        if chosen_idx is None:
            raise MemoryError(f"MioRomHeap out of memory: cannot allocate {needed} bytes")

        target_block = self.blocks[chosen_idx]
        remaining = target_block.size - needed - BLOCK_HEADER_SIZE

        if remaining >= ALIGNMENT:
            # Split block
            allocated_block = MemBlock(
                offset=target_block.offset,
                size=needed,
                is_allocated=True,
                prev_offset=target_block.prev_offset,
                next_offset=target_block.offset + BLOCK_HEADER_SIZE + needed,
            )
            free_block = MemBlock(
                offset=allocated_block.next_offset,
                size=remaining,
                is_allocated=False,
                prev_offset=allocated_block.offset,
                next_offset=target_block.next_offset,
            )

            self.blocks[chosen_idx] = allocated_block
            self.blocks.insert(chosen_idx + 1, free_block)

            self._write_block_header(allocated_block)
            self._write_block_header(free_block)
            return self.base_ram + allocated_block.offset + BLOCK_HEADER_SIZE
        else:
            # Take entire block
            target_block.is_allocated = True
            self._write_block_header(target_block)
            return self.base_ram + target_block.offset + BLOCK_HEADER_SIZE

    def free(self, ram_addr: int) -> bool:
        """
        Free a previously allocated block at `ram_addr`.
        Coalesces adjacent free blocks.
        """
        target_offset = (ram_addr - self.base_ram) - BLOCK_HEADER_SIZE
        if target_offset < 0 or target_offset >= self.total_size:
            return False

        target_idx = None
        for idx, block in enumerate(self.blocks):
            if block.offset == target_offset:
                target_idx = idx
                break

        if target_idx is None or not self.blocks[target_idx].is_allocated:
            return False

        self.blocks[target_idx].is_allocated = False
        self._write_block_header(self.blocks[target_idx])

        # Coalesce with next block if free
        if target_idx + 1 < len(self.blocks) and not self.blocks[target_idx + 1].is_allocated:
            next_b = self.blocks[target_idx + 1]
            self.blocks[target_idx].size += BLOCK_HEADER_SIZE + next_b.size
            self.blocks[target_idx].next_offset = next_b.next_offset
            self.blocks.pop(target_idx + 1)
            self._write_block_header(self.blocks[target_idx])

        # Coalesce with prev block if free
        if target_idx > 0 and not self.blocks[target_idx - 1].is_allocated:
            prev_b = self.blocks[target_idx - 1]
            cur_b = self.blocks[target_idx]
            prev_b.size += BLOCK_HEADER_SIZE + cur_b.size
            prev_b.next_offset = cur_b.next_offset
            self.blocks.pop(target_idx)
            self._write_block_header(prev_b)

        return True

    def stats(self) -> HeapStats:
        """Calculate heap memory usage statistics."""
        used = 0
        free = 0
        allocs = 0
        largest_free = 0

        for b in self.blocks:
            if b.is_allocated:
                used += b.size + BLOCK_HEADER_SIZE
                allocs += 1
            else:
                free += b.size
                if b.size > largest_free:
                    largest_free = b.size

        frag = 1.0 - (largest_free / free) if free > 0 else 0.0

        return HeapStats(
            total_size=self.total_size,
            used_bytes=used,
            free_bytes=free,
            num_allocations=allocs,
            largest_free_block=largest_free,
            fragmentation_ratio=max(0.0, frag),
        )

    def check_integrity(self) -> bool:
        """Verify headers and integrity across the entire heap buffer."""
        for b in self.blocks:
            magic, sz, flags, nxt = struct.unpack_from(">IIII", self.buffer, b.offset)
            if magic != HEAP_MAGIC:
                return False
            if sz != b.size:
                return False
        return True

    def generate_c_payload(self) -> str:
        """
        Generate self-contained C source code for the in-ROM heap allocator.
        Suitable for compiling with GCC into an ELF payload for ElfInjector.
        """
        return f"""/* Auto-generated by MioRomHeap (MioROM Linker SDK) */
#include <stdint.h>
#include <stddef.h>

#define MIO_HEAP_BASE   ((uint8_t*)0x{self.base_ram:08X})
#define MIO_HEAP_SIZE   0x{self.total_size:08X}
#define MIO_MAGIC       0x4D494F48

typedef struct MioBlockHeader {{
    uint32_t magic;
    uint32_t size;
    uint32_t is_allocated;
    struct MioBlockHeader* next;
}} MioBlockHeader;

static MioBlockHeader* g_root_block = (MioBlockHeader*)0x{self.base_ram:08X};

void miorom_heap_init(void) {{
    g_root_block->magic = MIO_MAGIC;
    g_root_block->size = MIO_HEAP_SIZE - sizeof(MioBlockHeader);
    g_root_block->is_allocated = 0;
    g_root_block->next = NULL;
}}

void* miorom_malloc(size_t size) {{
    size = (size + 15) & ~15;
    MioBlockHeader* curr = g_root_block;
    while (curr) {{
        if (!curr->is_allocated && curr->size >= size) {{
            if (curr->size >= size + sizeof(MioBlockHeader) + 16) {{
                MioBlockHeader* next_b = (MioBlockHeader*)((uint8_t*)curr + sizeof(MioBlockHeader) + size);
                next_b->magic = MIO_MAGIC;
                next_b->size = curr->size - size - sizeof(MioBlockHeader);
                next_b->is_allocated = 0;
                next_b->next = curr->next;
                curr->next = next_b;
                curr->size = size;
            }}
            curr->is_allocated = 1;
            return (void*)((uint8_t*)curr + sizeof(MioBlockHeader));
        }}
        curr = curr->next;
    }}
    return NULL;
}}

void miorom_free(void* ptr) {{
    if (!ptr) return;
    MioBlockHeader* header = (MioBlockHeader*)((uint8_t*)ptr - sizeof(MioBlockHeader));
    if (header->magic != MIO_MAGIC) return;
    header->is_allocated = 0;
    
    // Coalesce adjacent free blocks
    MioBlockHeader* curr = g_root_block;
    while (curr && curr->next) {{
        if (!curr->is_allocated && !curr->next->is_allocated) {{
            curr->size += sizeof(MioBlockHeader) + curr->next->size;
            curr->next = curr->next->next;
        }} else {{
            curr = curr->next;
        }}
    }}
}}
"""
