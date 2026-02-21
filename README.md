
# SQL Optimizer Agent (MVP) — `qagent`

A minimal CLI agent that benchmarks a SQL query on a local DuckDB database, asks an LLM to propose an optimized rewrite, rebenchmarks the candidate, and stops once it reaches an improvement threshold or hits `--max-iters`.

---

## 1) Install & Configure

### 1.1 Prerequisites
- Python 3.10+ (recommended)
- DuckDB (Python package)
- An OpenAI API key 


### 1.2 Install the CLI

If this repo is packaged (recommended), install in editable mode:

```
pip install -e .
```

After installation, confirm the CLI is available:
```
qagent --help
qagent optimize --help
```

### 1.3 Configure OpenAI credentials

Set your API key in environment variables:
```
export OPENAI_API_KEY="YOUR_KEY_HERE"
```


## 2) Database Setup (MIMIC-IV on DuckDB)

This project assumes you already have a DuckDB database file built from MIMIC-IV (or any other database). You only need:

- A DuckDB .db file path

The tables referenced by the SQL (e.g. mimiciv_icu.icustays, mimiciv_icu.chartevents, mimiciv_hosp.labevents)

[what is mimic dataset]


## 3) Quick Run 

Run the optimizer against a query file:

qagent \
  --db /Users/chloe/Desktop/healthcare/mimic-iv-3.1/buildmimic/duckdb/mimic4.db \
  --query-file /Users/chloe/Desktop/uw_madison/26Spring/AI_Agent/sql-optimizer-agent/src/test/bad.sql \
  --max-iters 2

What you should see:

- A baseline benchmark (median execution time)

- One or more iterations where the model proposes a candidate rewrite

- A candidate benchmark (median execution time + improvement %)

- A final best SQL + best report summary



## 4) How the Agent Works 

At a high level, qagent optimize does the following:

Load input query

Reads SQL from --query-file (or --query if supported)

Baseline benchmark

Runs a small benchmark loop (e.g., warmup + N runs)

Reports elapsed_ms and median_ms

Captures an EXPLAIN ANALYZE sample for profiling context

Optimization loop (up to --max-iters)

Sends the original SQL + profiling context to the LLM

The LLM returns a rewritten SQL candidate and a short rationale

The agent benchmarks the candidate SQL the same way

If improvement ≥ threshold, stop early; else continue

Pick best candidate

Tracks the best-performing SQL across iterations

Outputs:

Best SQL (final)

Best report (bench numbers + model text)

Notes for MVP:

Improvements are validated via measured runtime, not by LLM claims.

The agent currently focuses on runtime, not semantic equivalence checks.
