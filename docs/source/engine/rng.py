from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class SeededRNG(Generic[T]):
    seed: int | None = None
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)

    def shuffle(self, items: list[T]) -> list[T]:
        shuffled = list(items)
        self._random.shuffle(shuffled)
        return shuffled

    def draw_without_replacement(self, deck: list[T], count: int) -> list[T]:
        if count > len(deck):
            raise ValueError(f"Cannot draw {count} items from deck of size {len(deck)}.")

        drawn: list[T] = []
        for _ in range(count):
            index = self._random.randrange(len(deck))
            drawn.append(deck.pop(index))
        return drawn

