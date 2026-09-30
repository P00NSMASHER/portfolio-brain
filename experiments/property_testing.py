"""Small deterministic property checks for bounded local invariants."""
from __future__ import annotations

import random
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

MAX_EXAMPLES = 10_000
MAX_SHRINKS = 1_000


class PropertyCheckError(ValueError):
    pass


class PropertyFailure(AssertionError):
    def __init__(
        self,
        *,
        seed: int,
        example_index: int,
        counterexample: Any,
        minimized_counterexample: Any,
        examples_checked: int,
        shrinks_checked: int,
    ) -> None:
        self.seed = seed
        self.example_index = example_index
        self.counterexample = counterexample
        self.minimized_counterexample = minimized_counterexample
        self.examples_checked = examples_checked
        self.shrinks_checked = shrinks_checked
        super().__init__(
            f"property failed at example {example_index}; "
            f"counterexample={minimized_counterexample!r}; seed={seed}"
        )


def run_property(
    generate: Callable[[random.Random], T],
    predicate: Callable[[T], bool],
    *,
    seed: int,
    examples: int = 100,
    shrink: Callable[[T], Iterable[T]] | None = None,
    max_shrinks: int = 100,
) -> dict[str, Any]:
    if not callable(generate) or not callable(predicate):
        raise PropertyCheckError("generator and predicate must be callable")
    if type(seed) is not int:
        raise PropertyCheckError("seed must be an integer")
    if type(examples) is not int or not 1 <= examples <= MAX_EXAMPLES:
        raise PropertyCheckError(f"examples must be between 1 and {MAX_EXAMPLES}")
    if type(max_shrinks) is not int or not 0 <= max_shrinks <= MAX_SHRINKS:
        raise PropertyCheckError(f"max_shrinks must be between 0 and {MAX_SHRINKS}")
    if shrink is not None and not callable(shrink):
        raise PropertyCheckError("shrink must be callable")

    rng = random.Random(seed)
    for index in range(examples):
        value = generate(rng)
        result = predicate(value)
        if type(result) is not bool:
            raise PropertyCheckError("predicate must return bool")
        if result:
            continue

        minimized = value
        shrinks_checked = 0
        while shrink is not None and shrinks_checked < max_shrinks:
            reduced = False
            for candidate in shrink(minimized):
                if shrinks_checked >= max_shrinks:
                    break
                shrinks_checked += 1
                candidate_result = predicate(candidate)
                if type(candidate_result) is not bool:
                    raise PropertyCheckError("predicate must return bool")
                if not candidate_result:
                    minimized = candidate
                    reduced = True
                    break
            if not reduced:
                break
        raise PropertyFailure(
            seed=seed,
            example_index=index,
            counterexample=value,
            minimized_counterexample=minimized,
            examples_checked=index + 1,
            shrinks_checked=shrinks_checked,
        )

    return {"seed": seed, "examples_checked": examples, "status": "PASSED"}
