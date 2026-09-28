"""Immutable configuration, validation, and candidate counting."""

from dataclasses import dataclass
from itertools import chain
from string import ascii_lowercase, ascii_uppercase, digits, punctuation
from typing import Callable


@dataclass(frozen=True)
class Config:
    mode: str = "exhaustive"
    min_length: int = 4
    max_length: int = 4
    lowercase: bool = True
    uppercase: bool = False
    digits: bool = True
    symbols: bool = False
    extra_chars: str = ""
    exclude_chars: str = ""
    words: tuple[str, ...] = ()
    combine_words: bool = False
    substitutions: tuple[tuple[str, str], ...] = ()
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    case_variants: bool = False
    deduplicate: bool = False
    gzip_output: bool = False
    workers: int = 1


def alphabet(config: Config) -> str:
    groups = chain(
        ascii_lowercase if config.lowercase else "",
        ascii_uppercase if config.uppercase else "",
        digits if config.digits else "",
        punctuation if config.symbols else "",
        config.extra_chars,
    )
    return "".join(dict.fromkeys(c for c in groups if c not in config.exclude_chars))


def needs_deduplication(config: Config) -> bool:
    """Exhaustive products of a unique alphabet cannot contain duplicates."""
    return config.deduplicate and config.mode == "rules"


def validate(config: Config) -> None:
    if config.mode not in ("exhaustive", "rules"):
        raise ValueError("Select exhaustive or rule based generation.")
    if not (1 <= config.min_length <= config.max_length <= 32):
        raise ValueError("Lengths must satisfy 1 <= minimum <= maximum <= 32.")
    if not (1 <= config.workers <= 32):
        raise ValueError("Workers must be between 1 and 32.")
    if any("\n" in value or "\r" in value for value in (
        config.extra_chars, config.exclude_chars, *config.words, *config.prefixes,
        *config.suffixes, *(item for pair in config.substitutions for item in pair),
    )):
        raise ValueError("Entries must not contain line breaks.")
    if config.mode == "exhaustive" and not alphabet(config):
        raise ValueError("Select a character group or add custom characters.")
    if config.mode == "rules":
        if not config.words or any(not word for word in config.words):
            raise ValueError("Enter at least one nonempty base word for rule mode.")
        if any(not source or len(source) != 1 or not target or len(target) != 1
               for source, target in config.substitutions):
            raise ValueError("Each substitution must map one character to one character.")


def word_bases(config: Config):
    """Yield bases without materializing the ordered pair combinations."""
    yield from config.words
    if config.combine_words:
        for first in config.words:
            for second in config.words:
                yield first + second


def _case_forms(base: str, enabled: bool) -> tuple[str, ...]:
    if not enabled:
        return (base,)
    return tuple(dict.fromkeys((base, base.lower(), base.upper(), base.title())))


def replacement_options(character: str, substitutions: tuple[tuple[str, str], ...]):
    return tuple(dict.fromkeys((character, *(target for source, target in substitutions
                                            if source == character))))


def allowed_mutations(form: str, config: Config) -> tuple[tuple[str, ...], ...]:
    """Exclude disallowed characters before expanding the Cartesian product."""
    excluded = set(config.exclude_chars)
    return tuple(tuple(value for value in replacement_options(character, config.substitutions)
                       if value not in excluded) for character in form)


class EstimateCancelled(Exception):
    """An obsolete UI estimate stopped before completing its rule expansion."""


@dataclass(frozen=True)
class OutputEstimate:
    candidates: int
    plain_bytes: int


def estimate_output(config: Config, cancelled: Callable[[], bool] | None = None) -> OutputEstimate:
    """Exact candidate count and UTF-8 output bytes before optional deduplication."""
    validate(config)
    if config.mode == "exhaustive":
        pool = alphabet(config)
        size = len(pool)
        character_bytes = sum(len(char.encode("utf-8")) for char in pool)
        counts = ((length, size ** length) for length in
                  range(config.min_length, config.max_length + 1))
        total = 0
        plain_bytes = 0
        for length, count in counts:
            total += count
            plain_bytes += count + length * size ** (length - 1) * character_bytes
        return OutputEstimate(total, plain_bytes)

    total = 0
    plain_bytes = 0
    prefixes = ("", *config.prefixes)
    suffixes = ("", *config.suffixes)
    excluded = set(config.exclude_chars)
    for base in word_bases(config):
        if cancelled is not None and cancelled():
            raise EstimateCancelled()
        for form in _case_forms(base, config.case_variants):
            variants = 1
            option_bytes = []
            for options in allowed_mutations(form, config):
                variants *= len(options)
                option_bytes.append((len(options), sum(len(value.encode("utf-8"))
                                                       for value in options)))
            if not variants:
                continue
            mutated_bytes = sum(byte_count * (variants // option_count)
                                for option_count, byte_count in option_bytes)
            for prefix in prefixes:
                for suffix in suffixes:
                    if (config.min_length <= len(prefix) + len(form) + len(suffix) <= config.max_length
                            and not any(char in excluded for char in prefix + suffix)):
                        total += variants
                        plain_bytes += mutated_bytes + variants * (
                            len(prefix.encode("utf-8")) + len(suffix.encode("utf-8")) + 1)
    return OutputEstimate(total, plain_bytes)


def estimate(config: Config, cancelled: Callable[[], bool] | None = None) -> int:
    """Exact emitted iterator steps before optional global deduplication."""
    return estimate_output(config, cancelled).candidates
