"""Shared human-readable estimates for the desktop and command-line interfaces."""

from .model import Config, OutputEstimate, needs_deduplication


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size:,} B"
    units = ("KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    index = min((size.bit_length() - 1) // 10 - 1, len(units) - 1)
    scaled = size / (1024 ** (index + 1))
    return f"{scaled:.2g} {units[index]}"


def format_duration(seconds: int) -> str:
    if seconds < 1:
        return "under 1 second"
    for unit, span in (("year", 31_557_600), ("day", 86_400),
                       ("hour", 3_600), ("minute", 60)):
        if seconds >= span:
            amount = (seconds + span - 1) // span
            return f"about {amount:,} {unit}{'' if amount == 1 else 's'}"
    return f"about {seconds:,} second{'' if seconds == 1 else 's'}"


def planning_rate(config: Config) -> int:
    """Conservative display assumption, in processed candidates per second."""
    if needs_deduplication(config):
        return 100_000
    base = 500_000 if config.gzip_output else 1_000_000
    return base * (2 + min(config.workers - 1, 6)) // 2


def estimated_file_size(config: Config, result: OutputEstimate) -> str:
    if config.gzip_output:
        compressed = result.plain_bytes // 2 + 20
        return (f"~{format_size(compressed)} "
                "(assumes 50% gzip compression, before deduplication)")
    if needs_deduplication(config):
        return f"up to {format_size(result.plain_bytes)} (before deduplication)"
    return format_size(result.plain_bytes)
