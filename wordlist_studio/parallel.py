"""Bounded, ordered work units for CPU parallel candidate generation."""

from itertools import product, repeat

from .model import Config, _case_forms, allowed_mutations, alphabet, word_bases


BATCH_SIZE = 50_000


def tasks(config: Config, batch_size: int = BATCH_SIZE):
    """Yield small Cartesian-product slices in the same order as candidates()."""
    if config.mode == "exhaustive":
        pool = tuple(alphabet(config))
        for length in range(config.min_length, config.max_length + 1):
            yield from _slices("", "", tuple(repeat(pool, length)), batch_size)
        return

    prefixes = ("", *config.prefixes)
    suffixes = ("", *config.suffixes)
    excluded = set(config.exclude_chars)
    for base in word_bases(config):
        for form in _case_forms(base, config.case_variants):
            options = allowed_mutations(form, config)
            if any(not choices for choices in options):
                continue
            for prefix in prefixes:
                for suffix in suffixes:
                    if (config.min_length <= len(prefix) + len(form) + len(suffix) <= config.max_length
                            and not any(char in excluded for char in prefix + suffix)):
                        yield from _slices(prefix, suffix, options, batch_size)


def _slices(prefix, suffix, options, batch_size):
    split = len(options)
    count = 1
    while split and count * len(options[split - 1]) <= batch_size:
        split -= 1
        count *= len(options[split])
    for fixed in product(*options[:split]):
        yield prefix + "".join(fixed), suffix, options[split:], count


def generate_batch(task, encoded: bool):
    """Run in a child process; return either UTF-8 lines or raw candidates."""
    prefix, suffix, options, count = task
    lines = [prefix + "".join(mutation) + suffix for mutation in product(*options)]
    if encoded:
        return count, ("\n".join(lines) + "\n").encode("utf-8")
    return count, lines
