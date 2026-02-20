from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .duckdb_tools import DuckDBTooling, TOOLS_SPEC
from .llm_openai import OpenAIResponsesLLM, LLMConfig
from .util import extract_table_refs

SYSTEM_PROMPT = """You are a SQL optimization agent for DuckDB.

Rules:
- Do NOT assume tables or columns. Use tools to check existence and schema.
- If the query references relations not found in DuckDB catalog, ask the user for definitions or how they are created.
- Use EXPLAIN and benchmark (EXPLAIN ANALYZE) to evaluate before/after.
- When calling tools, pass raw SQL only. Never include backticks, markdown headings, or commentary in tool arguments.
- Preserve semantics: do not add LIMIT, sampling, or approximations unless user explicitly allows.
- Prefer rewrites that reduce scanned columns/rows and intermediate join cardinality:
  - Avoid SELECT *
  - Push filters down
  - Pre-aggregate before joins when safe
  - Replace correlated subqueries with joins/CTEs
  - Deduplicate repeated subqueries
- Output: provide the optimized SQL and a short rationale. Keep it concise.

Evaluation:
- Compare median_ms from benchmark. Consider >=10% improvement meaningful.
"""

@dataclass
class AgentConfig:
    max_tool_steps: int = 30

class SQLAgent:
    def __init__(self, llm: OpenAIResponsesLLM, tooling: DuckDBTooling, cfg: AgentConfig):
        self.llm = llm
        self.tooling = tooling
        self.cfg = cfg
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _dispatch(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "list_tables":
            return self.tooling.list_tables()
        if name == "table_exists":
            return self.tooling.table_exists(**args)
        if name == "describe_relation":
            return self.tooling.describe_relation(**args)
        if name == "explain":
            return self.tooling.explain(**args)
        if name == "benchmark":
            return self.tooling.benchmark(**args)
        return {"ok": False, "error": f"Unknown tool: {name}", "name": name, "args": args}

    def run_tool_loop(self) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Executes model/tool loop until model returns a final text (no tool calls),
        or until max steps is reached.
        Returns (final_text, events_for_ui)
        """
        events: List[Dict[str, Any]] = []
        for _ in range(self.cfg.max_tool_steps):
            resp = self.llm.responses_create(self.messages, tools=TOOLS_SPEC)
            output_items = resp.get("output", []) if isinstance(resp, dict) else resp.output

            self.messages += output_items

            tool_calls: List[Dict[str, Any]] = []
            final_text_chunks: List[str] = []

            for item in output_items:
                if item.get("type") == "function_call":
                    tool_calls.append(item)
                elif item.get("type") == "message":
                    content = item.get("content", [])
                    if isinstance(content, list):
                        for c in content:
                            if c.get("type") in ("output_text", "text"):
                                final_text_chunks.append(c.get("text", ""))
                    elif isinstance(content, str):
                        final_text_chunks.append(content)

            if tool_calls:
                for call in tool_calls:
                    name = call.get("name")
                    args_str = call.get("arguments", "{}")
                    call_id = call.get("call_id") or call.get("id")

                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                    except Exception:
                        args = {}

                    events.append({"kind": "tool_call", "name": name, "args": args})
                    result = self._dispatch(name, args)
                    events.append({"kind": "tool_result", "name": name, "result": result})

                    # Feed tool output back
                    # self.messages.append(
                    #     {
                    #         "role": "tool",
                    #         "tool_call_id": call_id,
                    #         "content": json.dumps(result, ensure_ascii=False),
                    #     }
                    # )

                    self.messages.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result, ensure_ascii=False),
                        }
                    )
                continue

            final_text = "\n".join([t for t in final_text_chunks if t.strip()]).strip() or None
            if final_text:
                self.messages.append({"role": "assistant", "content": final_text})
            return final_text, events

        return "Stopped: reached max_tool_steps.", events

    def optimize_once(
        self,
        bad_sql: str,
        runs: int = 3,
        warmup: int = 1,
        timeout_s: int = 60,
        allow_semantic_change: bool = False,
    ) -> Dict[str, Any]:
        """
        One optimize round:
        - check referenced tables exist + describe
        - baseline benchmark
        - ask model for optimized SQL
        - candidate benchmark
        """
        table_refs = extract_table_refs(bad_sql)
        self.messages.append(
            {
                "role": "user",
                "content": (
                    "Task: optimize the following SQL for DuckDB.\n\n"
                    f"Allow semantic changes: {allow_semantic_change}\n"
                    f"Benchmark settings: runs={runs}, warmup={warmup}, timeout_s={timeout_s}\n\n"
                    "SQL:\n"
                    "```sql\n"
                    f"{bad_sql}\n"
                    "```"
                ),
            }
        )

        # Prompt the model to do existence/schema checks and benchmarking via tools.
        self.messages.append(
            {
                "role": "user",
                "content": (
                    "Before rewriting, verify referenced relations and gather schema using tools. "
                    "Then benchmark the baseline. After rewriting, benchmark again."
                ),
            }
        )

        final_text, events = self.run_tool_loop()
        return {"final_text": final_text, "events": events, "table_refs": table_refs}
