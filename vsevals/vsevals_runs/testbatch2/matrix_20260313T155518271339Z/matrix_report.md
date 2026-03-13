# Matrix Evaluation Report

- Suite: `suites/script30.yaml`
- Total runs: **18**
- Successful runs: **18**
- Failed runs: **0**
- Avg oracle score: **0.0000**

## Per-Run Table

| task | variant | model | status | score | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| BUG59 | P0 | `claudecode:claude-haiku-4-5` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 25834 | 10 | 3 | fail |
| BUG59 | P0 | `codex:gpt-5.2-codex` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 18741 | 9213 | 749 | fail |
| BUG59 | P1 | `claudecode:claude-haiku-4-5` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 29567 | 10 | 1 | fail |
| BUG59 | P1 | `codex:gpt-5.2-codex` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 11916 | 9238 | 410 | fail |
| BUG59 | P2 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_OK | 1.00 | 2 | 0 | 53254 | 10 | 3 | ok |
| BUG59 | P2 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_OK | 1.00 | 2 | 0 | 9320 | 9749 | 345 | ok |
| BUG59 | P3 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 2 | 31698 | 18 | 8 | fail |
| BUG59 | P3 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 15628 | 9918 | 711 | fail |
| BUG59 | P4 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 21993 | 10 | 1 | fail |
| BUG59 | P4 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 22641 | 9987 | 1090 | fail |
| BUG59 | P5 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_PARTIAL | 0.50 | 3 | 4 | 61342 | 42 | 16 | fail |
| BUG59 | P5 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_PARTIAL | 0.50 | 4 | 4 | 52269 | 54776 | 1933 | fail |
| BUG59 | P6 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_PARTIAL | 0.50 | 4 | 2 | 45927 | 26 | 8 | ok |
| BUG59 | P6 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_OK | 1.00 | 5 | 6 | 61660 | 79850 | 1992 | fail |
| BUG59 | P7 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 1 | 36753 | 18 | 14 | fail |
| BUG59 | P7 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_OK | 1.00 | 4 | 1 | 16304 | 20061 | 584 | fail |
| BUG59 | P8 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_PARTIAL | 0.50 | 1 | 3 | 52851 | 26 | 9 | ok |
| BUG59 | P8 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_OK | 1.00 | 7 | 6 | 52572 | 82066 | 1890 | fail |
