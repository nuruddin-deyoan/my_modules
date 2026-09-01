"""
pytui.py — a lightweight, dependency-free terminal UI toolkit.

Drop this single file into any project and import what you need.
No external packages required (stdlib only).

Features
--------
- ANSI colors & text styles (auto-disabled on non-tty / when NO_COLOR is set)
- Status printers: print_success / print_error / print_warning / print_info
- Headers, dividers / rules
- Boxes / panels (single, double, round, bold borders) with optional title
- Tables (with per-column alignment)
- Spinners (threaded, several animation styles) — usable as context manager
- Progress bars — usable as context manager
- Interactive inputs:
    * ask_text        - free text, with default + validator
    * ask_confirm      - yes/no
    * ask_password      - hidden input
    * ask_select       - arrow-key single-select menu (numeric fallback)
    * ask_multiselect   - arrow-key checkbox menu (numeric fallback)
- Layout helpers: center_text, columns

Quick start
-----------
    from pytui import *

    print_header("My App")
    print_success("Connected to server")

    with Spinner("Fetching data"):
        time.sleep(2)

    name = ask_text("What's your name?", default="Anonymous")
    if ask_confirm(f"Hi {name}, continue?"):
        choice = ask_select("Pick a flavor", ["Vanilla", "Chocolate", "Mint"])
        print_info(f"You picked {choice}")

Run this file directly to see a full demo:
    python pytui.py
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import getpass
import itertools
import threading
from typing import Any, Callable, Optional, Sequence


# ==========================================================================
# Color / capability detection
# ==========================================================================

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            os.system("")  # enables ANSI escape processing on modern Windows
        except Exception:
            pass
    return True


COLOR_ENABLED = _supports_color()


class C:
    """ANSI escape codes. All become '' automatically if color is disabled."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"
    STRIKE = "\033[9m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"

    @classmethod
    def _disable(cls) -> None:
        for name in list(vars(cls)):
            if name.isupper():
                setattr(cls, name, "")


if not COLOR_ENABLED:
    C._disable()

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string."""
    return _ANSI_RE.sub("", text)


def visible_len(text: str) -> int:
    """Length of a string as it would appear on screen (ignoring ANSI codes)."""
    return len(strip_ansi(text))


def colorize(text: str, *styles: str) -> str:
    """Wrap `text` in the given ANSI style codes, e.g. colorize('hi', C.RED, C.BOLD)."""
    if not styles or not COLOR_ENABLED:
        return text
    return "".join(styles) + text + C.RESET


def term_width(default: int = 80) -> int:
    return shutil.get_terminal_size((default, 24)).columns


# ==========================================================================
# Status printers / headers
# ==========================================================================

def print_success(msg: str) -> None:
    print(f"{colorize('✔', C.GREEN, C.BOLD)} {msg}")


def print_error(msg: str) -> None:
    print(f"{colorize('✘', C.RED, C.BOLD)} {msg}")


def print_warning(msg: str) -> None:
    print(f"{colorize('⚠', C.YELLOW, C.BOLD)} {msg}")


def print_info(msg: str) -> None:
    print(f"{colorize('ℹ', C.CYAN, C.BOLD)} {msg}")


def print_header(title: str, color: str = C.CYAN) -> None:
    width = term_width()
    print()
    print(colorize(title.upper().center(width), color, C.BOLD))
    print(colorize("─" * width, C.GRAY))


def divider(char: str = "─", color: str = C.GRAY, width: Optional[int] = None) -> None:
    width = width or term_width()
    print(colorize(char * width, color))


def rule(label: str, char: str = "─", color: str = C.GRAY) -> None:
    """A horizontal rule with a centered label, e.g. ── Section ──"""
    width = term_width()
    label_txt = f" {label} "
    pad = max(width - len(label_txt), 0)
    left, right = pad // 2, pad - pad // 2
    print(colorize(char * left, color) + colorize(label_txt, C.BOLD) + colorize(char * right, color))


# ==========================================================================
# Boxes / panels
# ==========================================================================

BORDERS = {
    "single": dict(tl="┌", tr="┐", bl="└", br="┘", h="─", v="│"),
    "double": dict(tl="╔", tr="╗", bl="╚", br="╝", h="═", v="║"),
    "round":  dict(tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│"),
    "bold":   dict(tl="┏", tr="┓", bl="┗", br="┛", h="━", v="┃"),
}


def panel(
    content: str,
    title: str = "",
    style: str = "round",
    color: str = C.CYAN,
    padding: int = 1,
    width: Optional[int] = None,
) -> None:
    """Draw a bordered box around `content` (multi-line strings supported)."""
    b = BORDERS.get(style, BORDERS["round"])
    lines = content.split("\n")
    content_width = max((visible_len(l) for l in lines), default=0)
    if width:
        content_width = max(content_width, width - 2 * padding)
    inner = content_width + 2 * padding

    top = f"{b['tl']}{b['h'] * inner}{b['tr']}"
    if title:
        t = f" {title} "
        offset = 2
        top = (
            b["tl"] + b["h"] * offset + t
            + b["h"] * max(inner - offset - visible_len(t), 0) + b["tr"]
        )
    bottom = f"{b['bl']}{b['h'] * inner}{b['br']}"

    print(colorize(top, color))
    for line in lines:
        fill = content_width - visible_len(line)
        row = " " * padding + line + " " * fill + " " * padding
        print(colorize(b["v"], color) + row + colorize(b["v"], color))
    print(colorize(bottom, color))


# ==========================================================================
# Tables
# ==========================================================================

def table(
    rows: Sequence[Sequence[Any]],
    headers: Optional[Sequence[str]] = None,
    color: str = C.CYAN,
    align: Optional[Sequence[str]] = None,
) -> None:
    """Render a simple table. `align` is per-column: 'l' (default), 'r', or 'c'."""
    all_rows = [[str(cell) for cell in r] for r in rows]
    if headers:
        all_rows = [list(headers)] + all_rows
    ncols = max((len(r) for r in all_rows), default=0)
    widths = [0] * ncols
    for r in all_rows:
        for i in range(ncols):
            cell = r[i] if i < len(r) else ""
            widths[i] = max(widths[i], visible_len(cell))

    def fmt_row(r, bold=False):
        cells = []
        for i in range(ncols):
            cell = r[i] if i < len(r) else ""
            a = align[i] if align and i < len(align) else "l"
            w = widths[i]
            if a == "r":
                cell = cell.rjust(w)
            elif a == "c":
                cell = cell.center(w)
            else:
                cell = cell.ljust(w)
            cells.append(colorize(cell, C.BOLD) if bold else cell)
        return " │ ".join(cells)

    sep = "─┼─".join("─" * w for w in widths)

    start = 0
    if headers:
        print(colorize(fmt_row(all_rows[0], bold=True), color))
        print(colorize(sep, C.GRAY))
        start = 1
    for r in all_rows[start:]:
        print(fmt_row(r))


# ==========================================================================
# Spinners
# ==========================================================================

SPINNER_STYLES = {
    "dots":   ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    "line":   ["-", "\\", "|", "/"],
    "bar":    ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█", "▉", "▊", "▋", "▌", "▍", "▎"],
    "arrow":  ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
    "moon":   ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
    "bounce": ["⠁", "⠂", "⠄", "⡀", "⢀", "⠠", "⠐", "⠈"],
}


class Spinner:
    """Threaded terminal spinner. Use directly or as a context manager.

        with Spinner("Working..."):
            do_something_slow()

        s = Spinner("Uploading", style="bar").start()
        ...
        s.stop("Upload complete")
    """

    def __init__(self, text: str = "Loading...", style: str = "dots",
                 color: str = C.CYAN, interval: float = 0.08):
        self.text = text
        self.frames = SPINNER_STYLES.get(style, SPINNER_STYLES["dots"])
        self.color = color
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._interactive = sys.stdout.isatty()

    def _spin(self) -> None:
        for frame in itertools.cycle(self.frames):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{colorize(frame, self.color, C.BOLD)} {self.text}")
            sys.stdout.flush()
            time.sleep(self.interval)

    def start(self) -> "Spinner":
        if not self._interactive:
            print(f"… {self.text}")
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self, final_text: Optional[str] = None, success: bool = True) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if self._interactive:
            clear = "\r" + " " * (visible_len(self.text) + 4) + "\r"
            sys.stdout.write(clear)
        if final_text:
            mark = colorize("✔", C.GREEN, C.BOLD) if success else colorize("✘", C.RED, C.BOLD)
            print(f"{mark} {final_text}")
        sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> bool:
        ok = exc_type is None
        self.stop(final_text=self.text if ok else f"{self.text} — failed", success=ok)
        return False


# ==========================================================================
# Progress bar
# ==========================================================================

class ProgressBar:
    """Determinate progress bar.

        bar = ProgressBar(total=100, label="Downloading")
        for i in range(100):
            do_chunk()
            bar.update(step=1)

    or as a context manager (auto-completes to 100% on exit):

        with ProgressBar(total=len(items), label="Processing") as bar:
            for item in items:
                process(item)
                bar.update()
    """

    def __init__(self, total: int, width: int = 40, label: str = "",
                 fill: str = "█", empty: str = "░", color: str = C.GREEN):
        self.total = max(total, 1)
        self.width = width
        self.label = label
        self.fill = fill
        self.empty = empty
        self.color = color
        self.n = 0

    def update(self, n: Optional[int] = None, step: int = 1) -> None:
        self.n = n if n is not None else self.n + step
        self.n = max(0, min(self.n, self.total))
        pct = self.n / self.total
        filled = int(self.width * pct)
        bar = self.fill * filled + self.empty * (self.width - filled)
        prefix = f"{self.label} " if self.label else ""
        line = f"\r{prefix}{colorize(bar, self.color)} {pct * 100:5.1f}% ({self.n}/{self.total})"
        sys.stdout.write(line)
        sys.stdout.flush()
        if self.n >= self.total:
            sys.stdout.write("\n")

    def __enter__(self) -> "ProgressBar":
        self.update(0)
        return self

    def __exit__(self, *a) -> bool:
        if self.n < self.total:
            self.update(self.total)
        return False


# ==========================================================================
# Interactive inputs
# ==========================================================================

def ask_text(
    prompt: str,
    default: Optional[str] = None,
    validate: Optional[Callable[[str], bool]] = None,
    error_msg: str = "Invalid input, try again.",
) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{colorize('?', C.CYAN, C.BOLD)} {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            raw = default
        if validate and not validate(raw):
            print_error(error_msg)
            continue
        return raw


def ask_confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{colorize('?', C.CYAN, C.BOLD)} {prompt} ({hint}): ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print_error("Please answer y or n.")


def ask_password(prompt: str = "Password") -> str:
    return getpass.getpass(f"{colorize('?', C.CYAN, C.BOLD)} {prompt}: ")


def _getch() -> str:
    """Read one keypress cross-platform. Returns a raw char or a token like
    'UP' / 'DOWN' / 'ENTER' / 'ESC' / 'SPACE'."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT"}.get(ch2, "")
        if ch == "\r":
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        if ch == " ":
            return "SPACE"
        return ch
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                rest = sys.stdin.read(2)
                return {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(rest, "ESC")
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch == " ":
                return "SPACE"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def ask_select(prompt: str, choices: Sequence[str], color: str = C.CYAN) -> str:
    """Interactive single-select menu, navigated with arrow keys + Enter.
    Falls back to a numbered prompt on non-interactive terminals."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _ask_select_fallback(prompt, choices)

    idx = 0
    n = len(choices)

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{n}A")
        for i, choice in enumerate(choices):
            marker = colorize("❯", color, C.BOLD) if i == idx else " "
            text = colorize(choice, color, C.BOLD) if i == idx else choice
            sys.stdout.write(f"\033[2K{marker} {text}\n")
        sys.stdout.flush()

    print(f"{colorize('?', color, C.BOLD)} {prompt} {colorize('(↑/↓ then Enter)', C.GRAY)}")
    try:
        render(first=True)
        while True:
            key = _getch()
            if key == "UP":
                idx = (idx - 1) % n
                render()
            elif key == "DOWN":
                idx = (idx + 1) % n
                render()
            elif key == "ENTER":
                break
            elif key == "ESC":
                raise KeyboardInterrupt
    except Exception:
        return _ask_select_fallback(prompt, choices)
    return choices[idx]


def _ask_select_fallback(prompt: str, choices: Sequence[str]) -> str:
    print(f"{colorize('?', C.CYAN, C.BOLD)} {prompt}")
    for i, c in enumerate(choices, 1):
        print(f"  {colorize(str(i), C.CYAN)}) {c}")
    while True:
        raw = input("Enter number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print_error("Invalid choice.")


def ask_multiselect(prompt: str, choices: Sequence[str], color: str = C.CYAN) -> list:
    """Interactive checkbox menu: ↑/↓ move, Space toggles, Enter confirms.
    Falls back to comma-separated numbers on non-interactive terminals."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return _ask_multiselect_fallback(prompt, choices)

    idx = 0
    n = len(choices)
    selected = [False] * n

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\033[{n}A")
        for i, choice in enumerate(choices):
            box = "◉" if selected[i] else "◯"
            marker = colorize("❯", color, C.BOLD) if i == idx else " "
            box_c = colorize(box, C.GREEN if selected[i] else C.GRAY)
            text = colorize(choice, C.BOLD) if i == idx else choice
            sys.stdout.write(f"\033[2K{marker} {box_c} {text}\n")
        sys.stdout.flush()

    print(f"{colorize('?', color, C.BOLD)} {prompt} {colorize('(↑/↓ move, Space toggle, Enter confirm)', C.GRAY)}")
    try:
        render(first=True)
        while True:
            key = _getch()
            if key == "UP":
                idx = (idx - 1) % n
                render()
            elif key == "DOWN":
                idx = (idx + 1) % n
                render()
            elif key == "SPACE":
                selected[idx] = not selected[idx]
                render()
            elif key == "ENTER":
                break
            elif key == "ESC":
                raise KeyboardInterrupt
    except Exception:
        return _ask_multiselect_fallback(prompt, choices)
    return [c for c, s in zip(choices, selected) if s]


def _ask_multiselect_fallback(prompt: str, choices: Sequence[str]) -> list:
    print(f"{colorize('?', C.CYAN, C.BOLD)} {prompt} (comma-separated numbers)")
    for i, c in enumerate(choices, 1):
        print(f"  {colorize(str(i), C.CYAN)}) {c}")
    while True:
        raw = input("Your choice(s): ").strip()
        try:
            picks = [int(x) for x in raw.split(",") if x.strip()]
            if picks and all(1 <= p <= len(choices) for p in picks):
                return [choices[p - 1] for p in picks]
        except ValueError:
            pass
        print_error("Invalid input.")


# ==========================================================================
# Layout helpers
# ==========================================================================

def center_text(text: str, width: Optional[int] = None) -> str:
    width = width or term_width()
    pad = max(width - visible_len(text), 0)
    return " " * (pad // 2) + text


def columns(items: Sequence[Any], col_width: int = 20, cols: Optional[int] = None) -> None:
    """Print items in a simple grid of fixed-width columns."""
    width = term_width()
    cols = cols or max(1, width // col_width)
    for i in range(0, len(items), cols):
        row = items[i:i + cols]
        print("".join(str(item).ljust(col_width) for item in row))

def spinnerLoader(text, s_time=1.5):
    with Spinner(text, style="dots"):
        time.sleep(s_time)


# ==========================================================================
# Demo
# ==========================================================================

if __name__ == "__main__":
    print_header("pytui demo")

    print_success("This is a success message")
    print_error("This is an error message")
    print_warning("This is a warning message")
    print_info("This is an info message")

    rule("Panels")
    panel("Simple round panel\nwith two lines", title="Round", style="round", color=C.CYAN)
    panel("Double-border panel", title="Double", style="double", color=C.MAGENTA)
    panel("Bold-border panel", title="Bold", style="bold", color=C.YELLOW)

    rule("Table")
    table(
        headers=["Name", "Role", "Score"],
        rows=[
            ["Ada", "Engineer", 98],
            ["Grace", "Admiral", 95],
            ["Alan", "Mathematician", 99],
        ],
        align=["l", "l", "r"],
    )

    rule("Spinner")
    with Spinner("Doing some work", style="dots"):
        time.sleep(1.5)

    rule("Progress bar")
    with ProgressBar(total=30, label="Processing") as bar:
        for _ in range(30):
            time.sleep(0.02)
            bar.update()

    rule("Inputs")
    name = ask_text("What's your name?", default="World")
    likes_color = ask_confirm(f"Nice to meet you, {name}. Do you like colored terminals?")
    fav = ask_select("Pick your favorite border style", ["single", "double", "round", "bold"])
    panel(f"{name} likes colored terminals: {likes_color}\nFavorite style: {fav}",
          title="Summary", style=fav, color=C.GREEN)

    print_success("Demo complete!")