"""Lazy combinatorial candidate generators."""

from itertools import product

from .model import Config, _case_forms, allowed_mutations, alphabet, word_bases


def candidates(config: Config):
    if config.mode == "exhaustive":
        pool = alphabet(config)
        for length in range(config.min_length, config.max_length + 1):
            for chars in product(pool, repeat=length):
                yield "".join(chars)
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
                        for mutation in product(*options):
                            yield prefix + "".join(mutation) + suffix
