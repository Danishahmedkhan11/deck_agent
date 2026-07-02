"""
Tolerant JSON parsing for LLM output.

Gemini 2.5 models spend part of their token budget on hidden "thinking", so a
response can hit MAX_TOKENS and truncate mid-JSON. `loads_tolerant` recovers the
largest valid prefix by cutting at the last complete top-level element and
closing any still-open brackets — so a truncated critic response still yields its
leading `score`/`assessment`, and a truncated notes array still yields the
complete leading objects.
"""
from __future__ import annotations

import json
from typing import Any


def loads_tolerant(text: str) -> Any | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1:]
        t = t.strip()

    # 1) straight parse
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 2) outermost bracket slice
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                break

    # 3) salvage a truncated document
    return _salvage(t)


def _salvage(text: str) -> Any | None:
    start = next((k for k, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return None

    stack: list[str] = []
    in_str = esc = False
    last_good: tuple[int, list[str]] | None = None

    for k in range(start, len(text)):
        ch = text[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if len(stack) == 1:            # just closed a child of the outer container
                last_good = (k + 1, list(stack))
        elif ch == "," and len(stack) == 1:  # a complete top-level element precedes this comma
            last_good = (k, list(stack))

    if last_good:
        cut, remaining = last_good
        candidate = text[start:cut] + "".join(reversed(remaining))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None
