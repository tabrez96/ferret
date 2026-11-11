"""Run the bank parsers over real statements in a local folder.

Usage: uv run python -m ferret.tools.check_real <dir>

Prints one line per PDF to the terminal. Writes nothing to disk and logs nothing. Statements
are never copied, and passwords are asked for interactively and kept only in memory.
"""

import argparse
import getpass
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from ferret.money import from_minor
from ferret.parsers import PARSERS, ParseError, Parser, find_parser
from ferret.pipeline.pdf import NotAPdf, PasswordRequired, first_page_text, open_pdf, unlock
from ferret.reconcile import reconcile


def check_file(path: Path, passwords: list[str], parsers: Sequence[Parser] = PARSERS) -> str:
    """One result line for one PDF. Raises PasswordRequired if no password opens it."""
    data = path.read_bytes()
    try:
        unlocked, _ = unlock(data, passwords)
    except NotAPdf:
        return f"{path.name}: not a PDF"
    try:
        with open_pdf(unlocked) as pdf:
            parser = find_parser(first_page_text(pdf), parsers)
            if parser is None:
                return f"{path.name}: unsupported"
            try:
                parsed = parser.parse(pdf)
            except ParseError as e:
                return f"{path.name}: parse error ({e})"
    except NotAPdf:
        return f"{path.name}: not a PDF"
    try:
        rec = reconcile(parsed)
    except ValueError as e:
        return f"{path.name}: parse error ({e})"
    cur = rec.currency
    debits = sum(1 for t in parsed.transactions if not t.is_credit)
    credits = len(parsed.transactions) - debits
    verdict = "reconciled" if rec.ok else "didnt_add_up"
    return (
        f"{path.name}: {verdict}, {len(parsed.transactions)} lines "
        f"({debits} debits, {credits} credits), "
        f"difference {from_minor(rec.difference, cur)} {cur}, "
        f"debits {from_minor(rec.parsed_debits, cur)} "
        f"vs printed {from_minor(rec.total_debits, cur)}, "
        f"credits {from_minor(rec.parsed_credits, cur)} "
        f"vs printed {from_minor(rec.total_credits, cur)}"
    )


def _ask(prompt: str) -> str:
    if not sys.stdin.isatty():
        return ""
    try:
        return getpass.getpass(prompt)
    except EOFError:
        return ""


def main(
    argv: Sequence[str] | None = None,
    *,
    ask: Callable[[str], str] = _ask,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m ferret.tools.check_real")
    parser.add_argument("dir", type=Path)
    args = parser.parse_args(argv)
    if not args.dir.is_dir():
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 2
    logging.disable(logging.CRITICAL)
    try:
        pdfs = sorted(p for p in args.dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        passwords: list[str] = []
        reconciled = didnt = 0
        for path in pdfs:
            while True:
                try:
                    line = check_file(path, passwords)
                    break
                except PasswordRequired:
                    pw = ask(f"Password for {path.name} (blank to skip): ")
                    if not pw:
                        line = f"{path.name}: locked, skipped"
                        break
                    passwords.append(pw)
            print(line, file=out)
            reconciled += ": reconciled," in line
            didnt += ": didnt_add_up," in line
        other = len(pdfs) - reconciled - didnt
        print(
            f"{len(pdfs)} files: {reconciled} reconciled, {didnt} didnt_add_up, {other} other",
            file=out,
        )
        return 0
    finally:
        logging.disable(logging.NOTSET)


if __name__ == "__main__":
    raise SystemExit(main())
