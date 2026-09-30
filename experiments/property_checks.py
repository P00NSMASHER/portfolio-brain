"""Bounded, reproducible property checks for generated local test cases."""
from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


class PropertyCheckError(AssertionError):
    def __init__(self, *, seed: int, example_index: int, counterexample: object) -> None:
        self.seed = seed
        self.example_index = example_index
        self.counterexample = counterexample
        super().__init__(
            f"property failed at example {example_index} with seed {seed}: "
            f"{counterexample!r}"
        )


def check_generated_cases(
    draw: Callable[[random.Random], T],
    predicate: Callable[[T], bool],
    *,
    examples: int,
    seed: int,
    shrink: Callable[[T], Iterable[T]] | None = None,
    max_shrinks: int = 100,
) -> int:
    if not callable(draw) or not callable(predicate):
        raise TypeError("draw and predicate must be callable")
    if type(examples) is not int or examples <= 0:
        raise ValueError("examples must be a positive integer")
    if type(seed) is not int:
        raise TypeError("seed must be an integer")
    if shrink is not None and not callable(shrink):
        raise TypeError("shrink must be callable")
    if type(max_shrinks) is not int or max_shrinks < 0:
        raise ValueError("max_shrinks must be a non-negative integer")

    rng = random.Random(seed)
    for index in range(examples):
        value = draw(rng)
        result = predicate(value)
        if type(result) is not bool:
            raise TypeError("predicate must return bool")
        if result:
            continue

        attempts = 0
        while shrink is not None and attempts < max_shrinks:
            reduced = False
            for candidate in shrink(value):
                if attempts >= max_shrinks:
                    break
                attempts += 1
                result = predicate(candidate)
                if type(result) is not bool:
                    raise TypeError("predicate must return bool")
                if not result:
                    value = candidate
                    reduced = True
                    break
            if not reduced:
                break
        raise PropertyCheckError(
            seed=seed,
            example_index=index,
            counterexample=value,
        )
    return examples
