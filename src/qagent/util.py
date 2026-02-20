from __future__ import annotations
import re
from typing import List

TABLE_REGEX = re.compile(
    r"""
    (?:
      from|join
    )\s+
    (?:
      (?P<schema>[a-zA-Z_][\w]*)\.
    )?
    (?P<table>[a-zA-Z_][\w]*)
    """,
    re.IGNORECASE | re.VERBOSE,
)

def extract_table_refs(sql: str) -> List[str]:
    """
    MVP table ref extractor: finds FROM/JOIN identifiers like schema.table or table.
    Limitations: won't catch quoted identifiers, subqueries with aliases, etc.
    Good enough for MVP prompting + follow-up questions.
    """
    refs = []
    for m in TABLE_REGEX.finditer(sql):
        schema = m.group("schema")
        table = m.group("table")
        refs.append(f"{schema}.{table}" if schema else table)
    # de-dup preserve order
    seen = set()
    out = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))
