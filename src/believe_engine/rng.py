from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TypeVar

from .state import require_integer

T = TypeVar("T")


class SeededRng:
    def __init__(self, seed: int) -> None:
        require_integer("seed", seed)
        self._rng = random.Random(seed)

    def shuffled(self, items: Sequence[T]) -> tuple[T, ...]:
        result = list(items)
        self._rng.shuffle(result)
        return tuple(result)
