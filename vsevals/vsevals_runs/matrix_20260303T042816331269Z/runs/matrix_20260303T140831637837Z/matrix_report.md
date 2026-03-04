# Matrix Evaluation Report

- Suite: `suites/script30.yaml`
- Total runs: **77**
- Successful runs: **65**
- Failed runs: **12**
- Avg oracle score: **0.7692**

## Per-Run Table

| task | variant | model | status | score | memory_signal | req_coverage | snippets | tools | latency_ms | prompt_tokens | completion_tokens | pytest |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| BUG60 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 20578 | 10 | 1 | - |
| BUG60 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 34060 | 10 | 1 | - |
| BUG60 | P2 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 2 | 27608 | 26 | 3 | - |
| BUG60 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 31842 | 10 | 1 | - |
| BUG60 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 45283 | 18 | 3 | - |
| BUG60 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 43990 | 18 | 2 | - |
| BUG60 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 4 | 58434 | 42 | 5 | - |
| BUG61 | P0 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 61957 | 10 | 3 | - |
| BUG61 | P1 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 73893 | 10 | 1 | - |
| BUG61 | P2 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 4 | 55902 | 42 | 16 | - |
| BUG61 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 70956 | 10 | 5 | - |
| BUG61 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 4 | 2 | 85375 | 26 | 7 | - |
| BUG61 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 54562 | 10 | 3 | - |
| BUG61 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 4 | 64310 | 34 | 9 | - |
| BUG62 | P0 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 76596 | 10 | 5 | - |
| BUG62 | P1 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 62650 | 10 | 2 | - |
| BUG62 | P2 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 3 | 34532 | 34 | 4 | - |
| BUG62 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 61296 | 10 | 4 | - |
| BUG62 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 40839 | 18 | 5 | - |
| BUG62 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 36598 | 18 | 4 | - |
| BUG62 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 50893 | 18 | 2205 | - |
| BUG63 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 50599 | 10 | 1 | - |
| BUG63 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 48000 | 10 | 8 | - |
| BUG63 | P2 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 1 | 38868 | 18 | 5 | - |
| BUG63 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 60960 | 10 | 4 | - |
| BUG63 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 71627 | 18 | 2 | - |
| BUG63 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 40946 | 18 | 2 | - |
| BUG63 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 28192 | 18 | 7 | - |
| BUG64 | P0 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 33279 | 10 | 1 | - |
| BUG64 | P1 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 97829 | 10 | 3 | - |
| BUG64 | P2 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 2 | 4 | 53874 | 26 | 10 | - |
| BUG64 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 51116 | 10 | 5 | - |
| BUG64 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 48167 | 18 | 4 | - |
| BUG64 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 27180 | 18 | 4 | - |
| BUG64 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 39880 | 18 | 2 | - |
| BUG65 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 48683 | 10 | 5 | - |
| BUG65 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 112210 | 10 | 4 | - |
| BUG65 | P2 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 2 | 45247 | 26 | 3 | - |
| BUG65 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 41871 | 10 | 5 | - |
| BUG65 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 2 | 165744 | 26 | 2209 | - |
| BUG65 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 54235 | 18 | 2 | - |
| BUG65 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 0 | 2 | 88315 | 18 | 4 | - |
| BUG66 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 38890 | 10 | 3 | - |
| BUG66 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 86958 | 10 | 7657 | - |
| BUG66 | P2 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 70982 | 18 | 737 | - |
| BUG66 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 36906 | 10 | 4 | - |
| BUG66 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 2 | 39485 | 26 | 7 | - |
| BUG66 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 35028 | 18 | 2 | - |
| BUG66 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 34957 | 18 | 5 | - |
| BUG67 | P0 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 76855 | 10 | 4628 | - |
| BUG67 | P1 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 75778 | 10 | 8 | - |
| BUG67 | P2 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 77225 | 10 | 5 | - |
| BUG67 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 73401 | 10 | 4 | - |
| BUG67 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_ATTEMPTED_NO_HITS | 0.00 | 4 | 1 | 54042 | 18 | 4 | - |
| BUG67 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 52862 | 18 | 4 | - |
| BUG67 | P6 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG68 | P0 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG68 | P1 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG68 | P2 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG68 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 55237 | 10 | 5 | - |
| BUG68 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 4 | 1 | 31717 | 18 | 2 | - |
| BUG68 | P5 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG68 | P6 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 2 | 64895 | 26 | 8 | - |
| BUG69 | P0 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG69 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 81718 | 10 | 3 | - |
| BUG69 | P2 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | RETRIEVAL_MISSED | 0.00 | 0 | 0 | 61246 | 10 | 1 | - |
| BUG69 | P3 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG69 | P4 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG69 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 7 | 2 | 105857 | 26 | 3 | - |
| BUG69 | P6 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG70 | P0 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG70 | P1 | `claudecode:claude-haiku-4-5` | ok | 0.0000 | NO_MEMORY_EXPECTED | 0.00 | 0 | 0 | 36347 | 10 | 5 | - |
| BUG70 | P2 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
| BUG70 | P3 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 2 | 0 | 35221 | 10 | 4 | - |
| BUG70 | P4 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_PARTIAL | 0.50 | 7 | 2 | 19872 | 18 | 6 | - |
| BUG70 | P5 | `claudecode:claude-haiku-4-5` | ok | 1.0000 | RETRIEVAL_OK | 1.00 | 4 | 1 | 31320 | 18 | 4 | - |
| BUG70 | P6 | `claudecode:claude-haiku-4-5` | error | - | - | - | 0 | 0 | 0 | - | - | - |
