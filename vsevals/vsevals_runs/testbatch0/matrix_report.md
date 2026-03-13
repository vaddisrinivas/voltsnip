# Matrix Evaluation Report

- Suite: `suites/script30.yaml`
- Total runs: **18**
- Successful runs: **18**
- Failed runs: **0**
- Avg oracle score: **0.0000**

## Per-Run Table

| task | variant | model | status | score | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| BUG55 | P0 | `claudecode:claude-haiku-4-5` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 12198 | 10 | 2 | fail |
| BUG55 | P0 | `codex:gpt-5.2-codex` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 12437 | 9133 | 154 | fail |
| BUG55 | P1 | `claudecode:claude-haiku-4-5` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 12206 | 10 | 3 | fail |
| BUG55 | P1 | `codex:gpt-5.2-codex` | ok | - | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 5109 | 9164 | 162 | fail |
| BUG55 | P2 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_OK | 1.00 | 2 | 0 | 22888 | 10 | 8 | fail |
| BUG55 | P2 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_OK | 1.00 | 2 | 0 | 6485 | 9847 | 211 | fail |
| BUG55 | P3 | `claudecode:claude-haiku-4-5` | ok | - | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 5 | 75503 | 50 | 12 | fail |
| BUG55 | P3 | `codex:gpt-5.2-codex` | ok | - | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 16643 | 9841 | 748 | fail |
| BUG55 | P4 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 46971 | 10 | 8 | fail |
| BUG55 | P4 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 1 | 27973 | 20070 | 1278 | fail |
| BUG55 | P5 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 31360 | 18 | 2 | ok |
| BUG55 | P5 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 6 | 49021 | 76943 | 1579 | fail |
| BUG55 | P6 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 26363 | 18 | 2 | ok |
| BUG55 | P6 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 5 | 5 | 36008 | 72978 | 1300 | fail |
| BUG55 | P7 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 1 | 36096 | 18 | 4 | fail |
| BUG55 | P7 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 19280 | 19894 | 825 | fail |
| BUG55 | P8 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_OK | 1.00 | 4 | 2 | 30372 | 28 | 5 | ok |
| BUG55 | P8 | `codex:gpt-5.2-codex` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 1 | 19672 | 20019 | 734 | fail |
