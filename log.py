"""Colored logging helpers for mineru-enhanced."""

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


def _color() -> bool:
    """Whether stdout supports ANSI colors (respects NO_COLOR)."""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def banner(text: str) -> None:
    if _color():
        print(f"\n{_BOLD}{_CYAN}{text}{_RESET}")
    else:
        print(f"\n{text}")


def header(text: str) -> None:
    if _color():
        print(f"\n{_BOLD}--- {text} ---{_RESET}")
    else:
        print(f"\n--- {text} ---")


def progress(current: int, total: int, text: str = "") -> None:
    label = f"[{current}/{total}]"
    if _color():
        print(f"\n{_BOLD}{_CYAN}{label}{_RESET} {text}")
    else:
        print(f"\n{label} {text}")


def info(text: str) -> None:
    print(f"  {text}")


def detail(text: str) -> None:
    if _color():
        print(f"  {_DIM}{text}{_RESET}")
    else:
        print(f"  {text}")


def success(text: str) -> None:
    if _color():
        print(f"  {_GREEN}{text}{_RESET}")
    else:
        print(f"  {text}")


def warn(text: str) -> None:
    if _color():
        print(f"  {_YELLOW}Warning: {text}{_RESET}", file=sys.stderr)
    else:
        print(f"  Warning: {text}", file=sys.stderr)


def error(text: str) -> None:
    if _color():
        print(f"  {_RED}Error: {text}{_RESET}", file=sys.stderr)
    else:
        print(f"  Error: {text}", file=sys.stderr)


def kv(key: str, value: str) -> None:
    if _color():
        print(f"  {_BOLD}{key}:{_RESET} {value}")
    else:
        print(f"  {key}: {value}")
