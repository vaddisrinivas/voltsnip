# Matrix Evaluation Report

- Suite: `suites/script30.yaml`
- Total runs: **18**
- Successful runs: **18**
- Failed runs: **0**
- Avg oracle score: **0.0000**

## Per-Run Table

| task | variant | model | status | score | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| BUG48 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 25556 | 10 | 4 | fail |
| BUG48 | P0 | `codex:gpt-5.2-codex` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 42534 | 9193 | 2118 | fail |
| BUG48 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 43944 | 10 | 1 | fail |
| BUG48 | P1 | `codex:gpt-5.2-codex` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 43524 | 9222 | 2287 | fail |
| BUG48 | P2 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 64517 | 10 | 5 | fail |
| BUG48 | P2 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 8698 | 9936 | 247 | fail |
| BUG48 | P3 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 89216 | 10 | 1 | fail |
| BUG48 | P3 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 45210 | 9909 | 2358 | fail |
| BUG48 | P4 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 92201 | 10 | 1 | fail |
| BUG48 | P4 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 33201 | 9979 | 1676 | ok |
| BUG48 | P5 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 4 | 2 | 80050 | 26 | 8 | fail |
| BUG48 | P5 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 3 | 3 | 43883 | 43556 | 1865 | fail |
| BUG48 | P6 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 60749 | 10 | 3 | fail |
| BUG48 | P6 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 3 | 5 | 56956 | 75413 | 2100 | fail |
| BUG48 | P7 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_PARTIAL | 0.50 | 1 | 4 | 90825 | 42 | 12 | fail |
| BUG48 | P7 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 68659 | 20033 | 3588 | ok |
| BUG48 | P8 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 7 | 3 | 44137 | 28 | 5 | fail |
| BUG48 | P8 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 5 | 4 | 34208 | 55292 | 1413 | fail |
