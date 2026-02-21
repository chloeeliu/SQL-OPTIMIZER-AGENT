
# SQL Optimizer Agent (MVP) — `qagent`

A minimal CLI agent that benchmarks a SQL query on a local DuckDB database, asks an LLM to propose an optimized rewrite, rebenchmarks the candidate, and stops once it reaches an improvement threshold or hits `--max-iters`.

- inspects referenced relations (catalog + schema),
- benchmarks using `EXPLAIN ANALYZE`,
- proposes rewrite(s),
- rebenchmarks and reports performance improvement.

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


## 2) Database Setup (on DuckDB)

This project assumes you already have a DuckDB database file built from MIMIC-IV (or any other database). You only need:

- A DuckDB .db file path

The tables referenced by the SQL (e.g. mimiciv_icu.icustays, mimiciv_icu.chartevents, mimiciv_hosp.labevents)

[what is mimic dataset]


## 3) Quick Run 

Run the optimizer against a query file:
```
qagent \
  --db /Users/chloe/Desktop/healthcare/mimic-iv-3.1/buildmimic/duckdb/mimic4.db \
  --query-file /Users/chloe/Desktop/uw_madison/26Spring/AI_Agent/sql-optimizer-agent/src/test/bad.sql \
  --max-iters 2
```

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

## 5) Example: Successful Optimization (Bad vs Optimized)

### 5.1 Bad query

A typical “bad” query pattern in EHR analytics is selecting * and joining large event tables without limiting output columns:

```
SELECT *
FROM mimiciv_icu.icustays i
JOIN mimiciv_icu.chartevents ce
  ON ce.subject_id = i.subject_id
JOIN mimiciv_hosp.labevents le
  ON le.subject_id = i.subject_id
WHERE i.stay_id = 30008792
  AND ce.charttime BETWEEN i.intime AND i.outtime
  AND le.charttime BETWEEN i.intime AND i.outtime;
```

```
Query Profiling Summary
-----------------------
Total Time: 0.0167 s
Output Rows: 946,400


Execution Plan
---------------------------

PROJECTION
  Output: multiple columns from icustays, chartevents, labevents
  Rows: 946,400

HASH JOIN (INNER)
  Condition:
    subject_id = subject_id
    charttime >= intime
    charttime <= outtime
  Rows: 946,400
  Time: 0.01 s

  ├── TABLE SCAN: chartevents
  │     Type: Sequential Scan
  │     Rows: 5,600
  │
  └── HASH JOIN (INNER)
        Condition:
          subject_id = subject_id
          charttime BETWEEN intime AND outtime
        Rows: 169

        ├── TABLE SCAN: labevents
        │     Type: Sequential Scan
        │     Rows: 169
        │
        └── TABLE SCAN: icustays
              Type: Sequential Scan
              Filter: stay_id = 30008792
              Rows: 1
```

In one run, the baseline benchmark reported a median time around:
- **~17 ms median**

### 5.2 Optimized query (best SQL)
- Avoids SELECT *
- Moves time filters into join predicates
- Selects only relevant columns

```
SELECT
  i.subject_id, i.hadm_id, i.stay_id,
  i.first_careunit, i.last_careunit,
  i.intime, i.outtime, i.los,
  ce.charttime, ce.itemid, ce.value, ce.valuenum,
  le.charttime AS lab_charttime,
  le.itemid    AS lab_itemid,
  le.value     AS lab_value,
  le.valuenum  AS lab_valuenum
FROM mimiciv_icu.icustays i
JOIN mimiciv_icu.chartevents ce
  ON ce.subject_id = i.subject_id
 AND ce.charttime BETWEEN i.intime AND i.outtime
JOIN mimiciv_hosp.labevents le
  ON le.subject_id = i.subject_id
 AND le.charttime BETWEEN i.intime AND i.outtime
WHERE i.stay_id = 30008792;
```

In the same run, the candidate benchmark reported:

- **~11.5 ms** median
- **~33%** improvement over baseline
- Agent stopped early because improvement met the threshold.


```
Query Profiling Summary
-----------------------
Total Time: 0.0102 s
Output Rows: 946,400


Execution Plan
---------------------------
PROJECTION
  Columns:
    subject_id, hadm_id, stay_id,
    first_careunit, last_careunit,
    intime, outtime, los,
    charttime, itemid, value, valuenum,
    lab_charttime, lab_itemid, lab_value, lab_valuenum
  Rows: 946,400

└── HASH JOIN (INNER)
      Condition:
        subject_id = subject_id
        charttime BETWEEN intime AND outtime
      Rows: 946,400
      Time: 0.01 s

      ├── TABLE SCAN: chartevents
      │     Type: Sequential Scan
      │     Rows: 5,600
      │
      └── HASH JOIN (INNER)
            Condition:
              subject_id = subject_id
              charttime BETWEEN intime AND outtime
            Rows: 169

            ├── TABLE SCAN: labevents
            │     Type: Sequential Scan
            │     Rows: 169
            │
            └── TABLE SCAN: icustays
                  Type: Sequential Scan
                  Filter: stay_id = 30008792
                  Rows: 1
```


## Extention to Data Warehouse SQL Optimization
