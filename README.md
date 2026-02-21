
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

```pip install -e .```

After installation, confirm the CLI is available:
```
qagent --help
qagent optimize --help
```

### 1.3 Configure OpenAI credentials

Set your API key in environment variables:
``` export OPENAI_API_KEY="YOUR_KEY_HERE" ```
