"""JSON parsing helpers for LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str) -> Any:
    s = str(text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = s.strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = s.find(start_char)
        if start == -1:
            continue
        depth = 0
        end = -1
        for i in range(start, len(s)):
            if s[i] == start_char:
                depth += 1
            elif s[i] == end_char:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            continue
        candidate = s[start : end + 1]
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        candidate = re.sub(r"}\s*{", "},{", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Cannot parse JSON from LLM output: {s[:200]}")
