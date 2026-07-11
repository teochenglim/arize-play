"""Small ANSI console helpers so demo output reads well live, presented to
an audience -- degrades to plain text automatically when stdout isn't a
terminal (piped into a file, CI logs) or NO_COLOR is set."""
import os
import sys

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

_CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}


def _wrap(code_name: str, text: str) -> str:
    if not _ENABLED:
        return text
    return f"\033[{_CODES[code_name]}m{text}\033[0m"


def bold(text: str) -> str:
    return _wrap("bold", text)


def dim(text: str) -> str:
    return _wrap("dim", text)


def red(text: str) -> str:
    return _wrap("red", text)


def green(text: str) -> str:
    return _wrap("green", text)


def yellow(text: str) -> str:
    return _wrap("yellow", text)


def cyan(text: str) -> str:
    return _wrap("cyan", text)


def magenta(text: str) -> str:
    return _wrap("magenta", text)


def header(title: str):
    line = "─" * (len(title) + 4)
    print(f"\n{cyan(line)}")
    print(cyan(f"  {bold(title)}"))
    print(f"{cyan(line)}")


def section(label: str):
    print(f"\n{yellow('▶ ' + label)}")


def quote(text: str, indent: str = "    ") -> str:
    """Renders a chat-style message as a speech bubble, e.g. the user's
    question or the agent's reply, so it stands out from log lines."""
    lines = text.strip().splitlines() or [""]
    return "\n".join(f"{indent}{dim('│')} {line}" for line in lines)


def eval_line(name: str, result: dict):
    """One line per evaluator result, e.g. from binary_evaluator/
    code_evaluator/harness_judge -- all three return a dict with a
    'label' of 'pass'/'fail', a 'score', and an 'explanation'."""
    passed = result["label"] == "pass"
    badge = green("✔ PASS") if passed else red("✘ FAIL")
    score = result.get("score")
    score_str = dim(f" [{score}]") if score is not None else ""
    print(f"  {badge}{score_str}  {bold(name)}")
    print(f"      {dim(result['explanation'])}")


def verdict(result: dict) -> str:
    """Short colored PASS/FAIL for side-by-side summary tables."""
    return green("PASS") if result["label"] == "pass" else red("FAIL")
