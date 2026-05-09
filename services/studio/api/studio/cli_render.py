from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def color(text: object, code: str) -> str:
    return f"{code}{text}{_RESET}"


def ok(text: object) -> str:
    return color(text, _GREEN)


def warn(text: object) -> str:
    return color(text, _YELLOW)


def danger(text: object) -> str:
    return color(text, _RED)


def heading(text: object) -> str:
    return color(text, _BOLD + _CYAN)


def muted(text: object) -> str:
    return color(text, _DIM)


def visible_width(text: str) -> int:
    plain = _ANSI_RE.sub("", text)
    width = 0
    for char in plain:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_width(text))


def render_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    materialized = [["" if cell is None else str(cell) for cell in row] for row in rows]
    widths = [visible_width(header) for header in headers]
    for row in materialized:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], visible_width(cell))

    def line(left: str, sep: str, right: str, fill: str = "─") -> str:
        return left + sep.join(fill * (width + 2) for width in widths) + right

    def row(cells: Sequence[str]) -> str:
        return "│ " + " │ ".join(pad(cell, widths[idx]) for idx, cell in enumerate(cells)) + " │"

    out = [line("┌", "┬", "┐"), row([heading(header) for header in headers]), line("├", "┼", "┤")]
    if materialized:
        out.extend(row(row_cells) for row_cells in materialized)
    else:
        out.append(row([muted("empty"), *("" for _ in headers[1:])]))
    out.append(line("└", "┴", "┘"))
    return "\n".join(out)
