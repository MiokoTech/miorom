import random

import pytest

from miorom.scanner.table_detector import HeuristicTableDetector


@pytest.mark.benchmark(group="scanner")
def test_heuristic_pointer_table_benchmark(benchmark):
    random.seed(0x4D494F)
    data = bytes(random.randrange(256) for _ in range(256 * 1024))

    def run():
        return HeuristicTableDetector.detect_pointer_tables(data, min_entries=8)

    assert benchmark(run) == []
