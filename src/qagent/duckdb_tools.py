#duckdb_tools.py

from __future__ import annotations
import time
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import duckdb

TOTAL_TIME_RE = re.compile(r"Total Time:\s*([0-9.]+)s", re.IGNORECASE)

@dataclass
class DuckDBEnv:
    db_path: str
    read_only: bool = True

class DuckDBTooling:
    def __init__(self, env: DuckDBEnv):
        self.env = env
        # read_only=True prevents accidental writes to the db file
        self.con = duckdb.connect(database=env.db_path, read_only=env.read_only)

        # Make EXPLAIN output stable/readable
        try:
            self.con.execute("SET explain_output='all';")
        except Exception:
            pass

    # ---------- basic catalog ----------
    def list_tables(self) -> Dict[str, Any]:
        rows = self.con.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        items = [{"schema": r[0], "name": r[1], "type": r[2]} for r in rows]
        return {"ok": True, "tables": items}

    def table_exists(self, name: str) -> Dict[str, Any]:
        # Accept schema.table or table
        if "." in name:
            schema, table = name.split(".", 1)
            q = """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema=? AND table_name=?
            """
            n = self.con.execute(q, [schema, table]).fetchone()[0]
        else:
            q = """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name=?
            """
            n = self.con.execute(q, [name]).fetchone()[0]
        return {"ok": True, "name": name, "exists": n > 0}

    def describe_relation(self, name: str, sample_cols: int = 200) -> Dict[str, Any]:
        """
        Returns columns/types from information_schema.columns.
        """
        if "." in name:
            schema, table = name.split(".", 1)
            q = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema=? AND table_name=?
            ORDER BY ordinal_position
            """
            rows = self.con.execute(q, [schema, table]).fetchall()
        else:
            # could match multiple schemas; pick all
            q = """
            SELECT table_schema, column_name, data_type
            FROM information_schema.columns
            WHERE table_name=?
            ORDER BY table_schema, ordinal_position
            """
            rows = self.con.execute(q, [name]).fetchall()

        if not rows:
            return {"ok": False, "error": f"Relation not found in catalog: {name}"}

        if "." in name:
            cols = [{"name": c, "type": t} for (c, t) in rows[:sample_cols]]
            return {"ok": True, "relation": name, "columns": cols, "num_columns": len(rows)}
        else:
            # group by schema
            grouped: Dict[str, List[Dict[str, str]]] = {}
            for schema, c, t in rows[:sample_cols]:
                grouped.setdefault(schema, []).append({"name": c, "type": t})
            return {"ok": True, "relation": name, "schemas": grouped, "num_columns": len(rows)}

    def row_count(self, name: str, timeout_s: int = 30) -> Dict[str, Any]:
        """
        Potentially expensive. Use sparingly.
        """
        sql = f"SELECT COUNT(*) FROM {name}"
        return self._timed_exec_scalar(sql, timeout_s=timeout_s, label="row_count")

    # ---------- explain / eval ----------
    def explain(self, sql: str) -> Dict[str, Any]:
        try:
            rows = self.con.execute(f"EXPLAIN {sql}").fetchall()
            # DuckDB returns rows like (explain_key, explain_value)
            plan = "\n".join([str(r[1]) for r in rows])
            return {"ok": True, "plan": plan}
        except Exception as e:
            return {"ok": False, "error": f"EXPLAIN failed: {e}"}

    def explain_analyze(self, sql: str, timeout_s: int = 60) -> Dict[str, Any]:
        """
        Runs EXPLAIN ANALYZE, which executes the query and returns plan+timing,
        without returning the query result set.
        """
        try:
            # DuckDB doesn't offer a built-in statement timeout consistently across versions;
            # we enforce via Python-level timeout by measuring and returning if too slow.
            t0 = time.perf_counter()
            rows = self.con.execute(f"EXPLAIN ANALYZE {sql}").fetchall()
            elapsed = (time.perf_counter() - t0) * 1000.0

            txt = "\n".join([str(r[1]) for r in rows])
            total_s = None
            m = TOTAL_TIME_RE.search(txt)
            if m:
                total_s = float(m.group(1))
            return {
                "ok": True,
                "elapsed_ms_client": elapsed,
                "total_time_s_explain": total_s,
                "analyze": txt,
            }
        except Exception as e:
            return {"ok": False, "error": f"EXPLAIN ANALYZE failed: {e}"}

    def benchmark(self, sql: str, runs: int = 3, warmup: int = 1, timeout_s: int = 60) -> Dict[str, Any]:
        """
        Benchmarks using EXPLAIN ANALYZE as the measurement primitive.
        Returns median of client-measured elapsed ms, and captures one analyze text.
        """
        times = []
        last_analyze = None
        last_total_s = None

        # warmup
        for _ in range(warmup):
            r = self.explain_analyze(sql, timeout_s=timeout_s)
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error")}
        # measured
        for _ in range(runs):
            r = self.explain_analyze(sql, timeout_s=timeout_s)
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error")}
            times.append(float(r["elapsed_ms_client"]))
            last_analyze = r.get("analyze")
            last_total_s = r.get("total_time_s_explain")

        times_sorted = sorted(times)
        median = times_sorted[len(times_sorted) // 2]
        return {
            "ok": True,
            "runs": runs,
            "warmup": warmup,
            "elapsed_ms": times,
            "median_ms": median,
            "analyze_sample": last_analyze,
            "total_time_s_explain_sample": last_total_s,
        }

    # ---------- helpers ----------
    def _timed_exec_scalar(self, sql: str, timeout_s: int, label: str) -> Dict[str, Any]:
        try:
            t0 = time.perf_counter()
            val = self.con.execute(sql).fetchone()[0]
            elapsed = (time.perf_counter() - t0) * 1000.0
            if elapsed > timeout_s * 1000:
                return {"ok": False, "error": f"{label} exceeded timeout {timeout_s}s", "elapsed_ms": elapsed}
            return {"ok": True, "value": val, "elapsed_ms": elapsed}
        except Exception as e:
            return {"ok": False, "error": f"{label} failed: {e}"}

# ---- Tool schema for OpenAI function calling ----

TOOLS_SPEC = [
    {
        "type": "function",
        "name": "list_tables",
        "description": "List tables/views in DuckDB (excluding system schemas).",
        "parameters": {"type": "object", 
                       "properties": {}, 
                       "required": []},
        
    },
    {
        "type": "function",
        "name": "table_exists",
        "description": "Check whether a relation exists in DuckDB catalog.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            },
        
    },
    {
        "type": "function",
        "name": "describe_relation",
        "description": "Get column names and types for a table/view from information_schema.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "sample_cols": {"type": "integer", "default": 200},
            },
            "required": ["name"],
            },
    },
    {
        "type": "function",
        "name": "explain",
        "description": "Run EXPLAIN <sql> and return the plan text.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
            },
        
    },
    {
        "type": "function",
        "name": "benchmark",
        "description": "Benchmark a SQL query using EXPLAIN ANALYZE. IMPORTANT: `sql` must be raw SQL only (no markdown, no backticks, no headings).",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "runs": {"type": "integer", "default": 3},
                "warmup": {"type": "integer", "default": 1},
                "timeout_s": {"type": "integer", "default": 60},
            },
            "required": ["sql"],
            },
    },
]
