from __future__ import annotations
from pathlib import Path
import re
import typer
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.syntax import Syntax

from .duckdb_tools import DuckDBTooling, DuckDBEnv
from .llm_openai import OpenAIResponsesLLM, LLMConfig
from .agent import SQLAgent, AgentConfig

app = typer.Typer(add_completion=False)
console = Console()

SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)

def _extract_sql_from_model(text: str) -> str | None:
    if not text:
        return None
    m = SQL_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    # fallback: try whole text if it looks like SQL
    if "select" in text.lower():
        return text.strip()
    return None

@app.command()
def optimize(
    db: str = typer.Option(..., help="Path to DuckDB database file (e.g., mimic.db)"),
    query_file: str = typer.Option(None, help="Path to .sql file containing the bad query"),
    query: str = typer.Option(None, help="Bad SQL query as a string"),
    model: str = typer.Option("gpt-4o-mini", help="OpenAI model"),
    runs: int = typer.Option(3, help="Benchmark runs (median)"),
    warmup: int = typer.Option(1, help="Warmup runs"),
    timeout_s: int = typer.Option(60, help="Timeout for EXPLAIN ANALYZE (best-effort)"),
    max_iters: int = typer.Option(2, help="Max optimization iterations"),
    min_improve_pct: float = typer.Option(10.0, help="Stop if improvement >= this percent"),
):
    if not Path(db).exists():
        raise typer.BadParameter(f"DB file not found: {db}")

    if not query and not query_file:
        raise typer.BadParameter("Provide --query or --query-file")

    if query_file:
        qpath = Path(query_file)
        if not qpath.exists():
            raise typer.BadParameter(f"Query file not found: {query_file}")
        bad_sql = qpath.read_text(encoding="utf-8")
    else:
        bad_sql = query

    tooling = DuckDBTooling(DuckDBEnv(db_path=db, read_only=True))
    llm = OpenAIResponsesLLM(LLMConfig(model=model, max_output_tokens=1400))
    agent = SQLAgent(llm, tooling, AgentConfig(max_tool_steps=35))

    console.print(Panel.fit(f"[bold]qagent[/bold]\nDB: {db}\nModel: {model}", title="SQL Optimizer Agent (MVP)"))
    console.print(Panel(Syntax(bad_sql, "sql", word_wrap=True), title="Input SQL", border_style="cyan"))

    best_sql = bad_sql
    best_report = None

    # Baseline benchmark done directly (outside LLM) for a stable numeric reference
    base_bench = tooling.benchmark(best_sql, runs=runs, warmup=warmup, timeout_s=timeout_s)
    if not base_bench.get("ok"):
        console.print(Panel(str(base_bench), title="Baseline benchmark failed", border_style="red"))
        raise typer.Exit(code=1)

    base_ms = float(base_bench["median_ms"])
    console.print(Panel(Pretty(base_bench), title=f"Baseline benchmark (median_ms={base_ms:.2f})", border_style="green"))

    for it in range(1, max_iters + 1):
        console.print(Panel.fit(f"Iteration {it}/{max_iters}", border_style="yellow"))

        out = agent.optimize_once(
            best_sql,
            runs=runs,
            warmup=warmup,
            timeout_s=timeout_s,
            allow_semantic_change=False,
        )

        final_text = out.get("final_text") or ""
        console.print(Panel(final_text or "(no text)", title="Model output", border_style="cyan"))

        cand_sql = _extract_sql_from_model(final_text)
        if not cand_sql:
            console.print(Panel("No SQL block found in model output. Stopping.", border_style="red"))
            break

        console.print(Panel(Syntax(cand_sql, "sql", word_wrap=True), title="Candidate SQL", border_style="cyan"))

        cand_bench = tooling.benchmark(cand_sql, runs=runs, warmup=warmup, timeout_s=timeout_s)
        if not cand_bench.get("ok"):
            console.print(Panel(Pretty(cand_bench), title="Candidate benchmark failed", border_style="red"))
            # Keep best, but allow another iteration if model can try a different approach
            continue

        cand_ms = float(cand_bench["median_ms"])
        improve_pct = (base_ms - cand_ms) / base_ms * 100.0

        console.print(
            Panel(
                Pretty(cand_bench),
                title=f"Candidate benchmark (median_ms={cand_ms:.2f}, improve={improve_pct:.1f}%)",
                border_style="green" if improve_pct > 0 else "red",
            )
        )

        if cand_ms < base_ms:
            # update baseline reference to new best for subsequent iteration
            best_sql = cand_sql
            base_ms = cand_ms
            best_report = {"benchmark": cand_bench, "model_text": final_text, "improve_pct": improve_pct}

        if improve_pct >= min_improve_pct:
            console.print(Panel.fit(f"Reached improvement threshold: {improve_pct:.1f}% ≥ {min_improve_pct:.1f}%. Stopping.", border_style="green"))
            break

    console.print(Panel(Syntax(best_sql, "sql", word_wrap=True), title="Best SQL (final)", border_style="magenta"))
    if best_report:
        console.print(Panel(Pretty(best_report), title="Best report", border_style="magenta"))
