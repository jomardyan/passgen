"""Lazy combinatorial candidate generators."""

from itertools import product

from .model import Config, _case_forms, alphabet, replacement_options, word_bases


def candidates(config: Config):
    if config.mode == "exhaustive":
        pool = alphabet(config)
        for length in range(config.min_length, config.max_length + 1):
            for chars in product(pool, repeat=length):
                yield "".join(chars)
        return

    prefixes = ("", *config.prefixes)
    suffixes = ("", *config.suffixes)
    for base in word_bases(config):
        for form in _case_forms(base, config.case_variants):
            options = tuple(replacement_options(char, config.substitutions) for char in form)
            for prefix in prefixes:
                for suffix in suffixes:
                    if config.min_length <= len(prefix) + len(form) + len(suffix) <= config.max_length:
                        for mutation in product(*options):
                            candidate = prefix + "".join(mutation) + suffix
                            if not any(char in config.exclude_chars for char in candidate):
                                yield candidate
