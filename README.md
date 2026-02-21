
# SQL Optimizer Agent (MVP) — `qagent`

Coding agent focused on SQL optimization, with particular emphasis on DuckDB best practices. Because SQL performance is highly context-dependent, the agent retrieves schema metadata, row counts, and execution plan details to inform optimization decisions.


The tool operates as a CLI agent that benchmarks a SQL query on a local DuckDB database, asks an LLM to propose an optimized rewrite, rebenchmarks the candidate, and stops once it reaches an improvement threshold or hits `--max-iters`.

- inspects referenced relations (catalog + schema),
- benchmarks using `EXPLAIN ANALYZE`,
- proposes rewrite(s),
- rebenchmarks and reports performance improvement.

<img width="2298" height="1098" alt="image" src="https://github.com/user-attachments/assets/c4476f87-594b-4193-a984-593ab21b28a2" />


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

This project needs a DuckDB database file. For example, built from MIMIC-IV or any other database. You only need:

- A DuckDB .db file path

The tables referenced by the SQL (e.g. mimiciv_icu.icustays, mimiciv_icu.chartevents, mimiciv_hosp.labevents)

MIMIC-IV is a patient EHR dataset. 
https://github.com/MIT-LCP/mimic-code/tree/main/mimic-iv/buildmimic/duckdb


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

<img width="2488" height="310" alt="image" src="https://github.com/user-attachments/assets/3a2963f3-be22-4b3e-893d-d6780f13d956" />
<img width="1244" height="509" alt="image" src="https://github.com/user-attachments/assets/82cea6b6-ce61-4929-8798-7dbf15877d19" />
<img width="1239" height="481" alt="image" src="https://github.com/user-attachments/assets/1f46e1f1-70f4-447d-90af-f8164c92295b" />



```
User SQL → Plan Analysis → Rewrite → Benchmark → Compare → Iterate → Best Query
```

### 4.1 Tooling Architecture

The agent currently uses 5 core tools:

1️⃣ **list_tables**  
**Purpose:** Discover schema objects and establish database context.  
**Used when:** Unknown tables or schema awareness is needed.

2️⃣ **describe_relation**  
**Purpose:** Retrieve columns and types; infer join keys and filter candidates.  
**Why:** Schema awareness improves rewrite quality.

3️⃣ **explain**  
**Purpose:** Get logical and physical plans.  
**Detects:** Join explosions, full scans, non-sargable predicates, large aggregates, unnecessary sorts.  
**Note:** Primary reasoning signal.

4️⃣ **explain_analyze / benchmark**  
**Purpose:** Execute with timing to obtain ground-truth performance.  
**Key:** Relies on execution feedback, not heuristics.

5️⃣ **benchmark comparison (internal)**  
**Purpose:** Compare candidate vs. baseline, accept only improvements, track best variant.  
**Benefit:** Prevents regressions and hallucinated optimizations.




## 5) Example: Successful Optimization (Bad vs Optimized)

- Original: **~17 ms median**
- Optimized: **~11.5 ms** median
- Improvement: **~33%** over baseline



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

The current prototype uses DuckDB for convenience and reproducibility. **However, local relational databases are not the primary environment where SQL optimization creates meaningful value.**

Local relational databases such as DuckDB typically operate on single node execution and minimal concurrency, so most quires already run within seconds or minutes and manual optimization yields marginal benefit.

Modern warehouse engines (Snowflake, BigQuery, Redshift, Databricks, etc.) introduce optimization dimensions that do not exist in local engines:
- Partition pruning
- Clustering / sort keys
- File formats and compression
- Statistics availability
- Data locality

During my evaluation on real world warehouse workloads(internship), the agent demonstrated substantial performance improvements.
- 40%–79% runtime reduction across multiple production jobs
- Significant gains even for complex multi-join analytical queries
- Even complex 400+ line queries achieved meaningful improvements, although with slightly reduced consistency due to larger optimization search space.

<img width="2040" height="706" alt="image" src="https://github.com/user-attachments/assets/75bcd29e-bc41-4746-a40e-040db01188ba" />

The internship results validate that the approach is not only feasible but highly effective in real-world systems.

