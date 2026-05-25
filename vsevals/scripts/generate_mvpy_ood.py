#!/usr/bin/env python3
"""Generate real-world MVPy OOD tasks.

The tasks are intentionally not algorithm-katas. They are tiny core11 versions
of analytics/stdlib/pandas-like workloads: groupby, fixed Counter, rolling
windows, lookup joins, cache-cost rollups, and trace scoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
PINNED_MVPY_COMMIT = "671aecf"
PLAN = {"easy": 100, "medium": 200, "hard": 200}


@dataclass(frozen=True)
class Case:
    id: str
    band: str
    category: str
    difficulty: int
    prompt: str
    program: str
    stdout: str
    features: list[str]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "mvpy_ood_500")
    parser.add_argument("--mvpy-bin", type=Path)
    parser.add_argument("--seen-dir", type=Path, default=ROOT / "data" / "mvpy_research")
    args = parser.parse_args()

    mvpy = find_mvpy(args.mvpy_bin)
    seen = load_seen_hashes(args.seen_dir)
    used: set[str] = set()
    rows: list[dict] = []
    for band, count in PLAN.items():
        made = 0
        i = 0
        while made < count:
            case = make_case(f"mvpy_ood_{len(rows) + 1:05d}", band, i)
            i += 1
            digest = sha256_text(case.program)
            if digest in seen or digest in used:
                continue
            validate(case, mvpy)
            used.add(digest)
            rows.append(dataset_row(case, digest, mvpy))
            made += 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "ood_qwen.jsonl", rows)
    write_jsonl(args.out_dir / "analysis_qwen.jsonl", rows)
    manifest = {
        "dataset_id": "mvpy_ood_realworld_analytics_500",
        "count": len(rows),
        "split_plan": PLAN,
        "categories_by_band": {
            band: sorted({row["category"] for row in rows if row["difficulty_band"] == band})
            for band in PLAN
        },
        "source_seen_hashes": len(seen),
        "sha_disjoint_from_seen": True,
        "verifier_commit": PINNED_MVPY_COMMIT,
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def make_case(case_id: str, band: str, n: int) -> Case:
    builders: dict[str, list[Callable[[str, str, int], Case]]] = {
        "easy": [agent_cost_snapshot, quota_snapshot, subscription_snapshot, sla_snapshot],
        "medium": [groupby_revenue, rolling_window_sum, lookup_join_revenue, fixed_counter],
        "hard": [dataframe_pipeline, cc_trace_rollup, rolling_anomaly_dashboard, stdlib_counter_accumulate],
    }
    choices = builders[band]
    return choices[n % len(choices)](case_id, band, n)


def agent_cost_snapshot(case_id: str, band: str, n: int) -> Case:
    prompt_tokens = 1200 + n * 17
    output_tokens = 250 + n * 5
    cached_tokens = 300 + n * 7
    prompt_rate = 2 + n % 4
    output_rate = 8 + n % 5
    cache_rate = 1 + n % 3
    gross = prompt_tokens * prompt_rate + output_tokens * output_rate
    cache_credit = cached_tokens * cache_rate
    net = gross - cache_credit
    program = lines(
        f"prompt_tokens = {prompt_tokens}",
        f"output_tokens = {output_tokens}",
        f"cached_tokens = {cached_tokens}",
        f"prompt_rate = {prompt_rate}",
        f"output_rate = {output_rate}",
        f"cache_rate = {cache_rate}",
        "gross = add(mul(prompt_tokens, prompt_rate), mul(output_tokens, output_rate))",
        "cache_credit = mul(cached_tokens, cache_rate)",
        "print(gross)",
        "print(cache_credit)",
        "print(sub(gross, cache_credit))",
    )
    return mk(case_id, band, "agent_cost_snapshot", 1, program, [gross, cache_credit, net],
        f"Build a tiny agent-cost report. Given prompt={prompt_tokens}, output={output_tokens}, cached={cached_tokens}, rates {prompt_rate}/{output_rate}/{cache_rate}, print gross cost, cache credit, and net cost.",
        ["tokens", "cache", "cost", "add", "sub", "mul", "print"])


def quota_snapshot(case_id: str, band: str, n: int) -> Case:
    limit = 10_000 + n * 31
    used = 2_000 + n * 29
    incoming = 500 + n * 11
    projected = used + incoming
    remaining = limit - projected
    breach = 1 if limit < projected else 0
    program = lines(
        f"limit = {limit}",
        f"used = {used}",
        f"incoming = {incoming}",
        "projected = add(used, incoming)",
        "print(projected)",
        "print(sub(limit, projected))",
        "print(lt(limit, projected))",
    )
    return mk(case_id, band, "api_quota_projection", 1, program, [projected, remaining, breach],
        f"Make an API quota projection: limit {limit}, already used {used}, incoming batch {incoming}. Print projected usage, remaining quota, and breach flag.",
        ["quota", "comparison", "add", "sub", "lt", "print"])


def subscription_snapshot(case_id: str, band: str, n: int) -> Case:
    seats = 8 + n % 30
    seat_price = 12 + n % 9
    addons = 40 + n * 3
    credits = 10 + n % 25
    mrr = seats * seat_price + addons - credits
    program = lines(
        f"seats = {seats}",
        f"seat_price = {seat_price}",
        f"addons = {addons}",
        f"credits = {credits}",
        "seat_mrr = mul(seats, seat_price)",
        "gross_mrr = add(seat_mrr, addons)",
        "print(gross_mrr)",
        "print(sub(gross_mrr, credits))",
    )
    return mk(case_id, band, "subscription_mrr_snapshot", 1, program, [seats * seat_price + addons, mrr],
        f"Compute SaaS MRR from {seats} seats at {seat_price}, add-ons {addons}, and credits {credits}. Print gross MRR and net MRR.",
        ["billing", "mrr", "add", "sub", "mul", "print"])


def sla_snapshot(case_id: str, band: str, n: int) -> Case:
    p1 = 2 + n % 8
    p2 = 5 + n % 14
    p1_minutes = 30 + n % 20
    p2_minutes = 8 + n % 12
    budget = 200 + n * 3
    total = p1 * p1_minutes + p2 * p2_minutes
    breach = 1 if budget < total else 0
    program = lines(
        f"p1 = {p1}",
        f"p2 = {p2}",
        f"p1_minutes = {p1_minutes}",
        f"p2_minutes = {p2_minutes}",
        f"budget = {budget}",
        "total = add(mul(p1, p1_minutes), mul(p2, p2_minutes))",
        "print(total)",
        "print(lt(budget, total))",
    )
    return mk(case_id, band, "incident_sla_snapshot", 2, program, [total, breach],
        f"Summarize incident SLA load: {p1} P1 tickets at {p1_minutes} minutes and {p2} P2 tickets at {p2_minutes} minutes, budget {budget}. Print total load and breach flag.",
        ["sla", "incident", "comparison", "add", "mul", "lt", "print"])


def groupby_revenue(case_id: str, band: str, n: int) -> Case:
    rows = 9 + n % 8
    first_region = n % 3
    amount = 20 + n * 2
    step = 3 + n % 7
    sums = [0, 0, 0]
    region = first_region
    value = amount
    for _ in range(rows):
        sums[region] += value
        region = (region + 1) % 3
        value += step
    program = lines(
        "def regions():",
        f"    region = {first_region}",
        f"    remaining = {rows}",
        "    while remaining:",
        "        yield region",
        "        region = add(region, 1)",
        "        region = sub(region, mul(eq(region, 3), 3))",
        "        remaining = sub(remaining, 1)",
        "def amounts():",
        f"    amount = {amount}",
        f"    step = {step}",
        f"    remaining = {rows}",
        "    while remaining:",
        "        yield amount",
        "        amount = add(amount, step)",
        "        remaining = sub(remaining, 1)",
        "region_stream = regions()",
        "amount_stream = amounts()",
        "sum0 = 0",
        "sum1 = 0",
        "sum2 = 0",
        f"remaining = {rows}",
        "while remaining:",
        "    region = next(region_stream)",
        "    amount = next(amount_stream)",
        "    sum0 = add(sum0, mul(eq(region, 0), amount))",
        "    sum1 = add(sum1, mul(eq(region, 1), amount))",
        "    sum2 = add(sum2, mul(eq(region, 2), amount))",
        "    remaining = sub(remaining, 1)",
        "print(sum0)",
        "print(sum1)",
        "print(sum2)",
    )
    return mk(case_id, band, "pandas_groupby_revenue", 3, program, sums,
        f"Implement a tiny pandas-style groupby. There are {rows} sales rows; region ids cycle from {first_region}, amounts start at {amount} and increase by {step}. Print revenue sums for regions 0, 1, and 2.",
        ["pandas", "groupby", "generator", "eq", "mul", "while", "print"])


def rolling_window_sum(case_id: str, band: str, n: int) -> Case:
    count = 8 + n % 8
    start = 50 + n * 2
    delta = 4 + n % 6
    values = [start + i * delta for i in range(count)]
    total_windows = sum(values[i - 2] + values[i - 1] + values[i] for i in range(2, count))
    program = lines(
        "def values():",
        f"    value = {start}",
        f"    delta = {delta}",
        f"    remaining = {count}",
        "    while remaining:",
        "        yield value",
        "        value = add(value, delta)",
        "        remaining = sub(remaining, 1)",
        "stream = values()",
        "a = next(stream)",
        "b = next(stream)",
        f"remaining = {count - 2}",
        "total_windows = 0",
        "while remaining:",
        "    c = next(stream)",
        "    window = add(add(a, b), c)",
        "    total_windows = add(total_windows, window)",
        "    a = b",
        "    b = c",
        "    remaining = sub(remaining, 1)",
        "print(total_windows)",
        "print(next(stream))",
    )
    return mk(case_id, band, "rolling_window_metric", 3, program, [total_windows, "None"],
        f"Implement a rolling-window analytics helper. A metric stream has {count} values starting at {start}, increasing by {delta}. Sum every 3-value rolling window, then print exhausted next().",
        ["pandas", "rolling", "generator", "while", "add", "next", "print"])


def lookup_join_revenue(case_id: str, band: str, n: int) -> Case:
    rows = 8 + n % 9
    first_category = n % 3
    units = 2 + n % 5
    unit_step = 1 + n % 4
    rates = [2 + n % 5, 5 + n % 7, 9 + n % 11]
    total = 0
    category = first_category
    qty = units
    for _ in range(rows):
        total += qty * rates[category]
        category = (category + 1) % 3
        qty += unit_step
    program = lines(
        f"rate0 = {rates[0]}",
        f"rate1 = {rates[1]}",
        f"rate2 = {rates[2]}",
        "def lookup_rate(category):",
        "    value = mul(eq(category, 0), rate0)",
        "    value = add(value, mul(eq(category, 1), rate1))",
        "    value = add(value, mul(eq(category, 2), rate2))",
        "    return value",
        f"category = {first_category}",
        f"units = {units}",
        f"unit_step = {unit_step}",
        f"remaining = {rows}",
        "total = 0",
        "while remaining:",
        "    total = add(total, mul(units, lookup_rate(category)))",
        "    category = add(category, 1)",
        "    category = sub(category, mul(eq(category, 3), 3))",
        "    units = add(units, unit_step)",
        "    remaining = sub(remaining, 1)",
        "print(total)",
    )
    return mk(case_id, band, "lookup_join_revenue", 4, program, [total],
        f"Implement a tiny lookup join. {rows} fact rows cycle product category from {first_category}; units start at {units}, grow by {unit_step}; category rates are {rates[0]}, {rates[1]}, {rates[2]}. Print joined revenue.",
        ["pandas", "join", "lookup", "eq", "while", "def", "return", "print"])


def fixed_counter(case_id: str, band: str, n: int) -> Case:
    rows = 10 + n % 12
    start = n % 3
    severity = 5 + n
    counts = [0, 0, 0]
    weighted = 0
    status = start
    current_severity = severity
    for _ in range(rows):
        counts[status] += 1
        weighted += current_severity * (status + 1)
        status = (status + 2) % 3
        current_severity += 1
    program = lines(
        f"status = {start}",
        f"severity = {severity}",
        f"remaining = {rows}",
        "ok = 0",
        "retry = 0",
        "fail = 0",
        "weighted = 0",
        "while remaining:",
        "    ok = add(ok, eq(status, 0))",
        "    retry = add(retry, eq(status, 1))",
        "    fail = add(fail, eq(status, 2))",
        "    weighted = add(weighted, mul(severity, add(status, 1)))",
        "    status = add(status, 2)",
        "    status = sub(status, mul(lt(2, status), 3))",
        "    severity = add(severity, 1)",
        "    remaining = sub(remaining, 1)",
        "print(ok)",
        "print(retry)",
        "print(fail)",
        "print(weighted)",
    )
    return mk(case_id, band, "collections_counter_status", 3, program, [*counts, weighted],
        f"Implement a fixed-size Counter like `collections.Counter`. {rows} API statuses start in bucket {start}; each next status advances by 2 modulo 3; severity starts {severity}. Print counts for ok, retry, fail, then weighted severity.",
        ["stdlib", "counter", "eq", "lt", "while", "add", "sub", "weighted_sum", "print"])


def dataframe_pipeline(case_id: str, band: str, n: int) -> Case:
    rows = 10 + n % 8
    first_region = n % 3
    price = 30 + n * 2
    units = 2 + n % 6
    price_step = 3 + n % 5
    unit_step = 1 + n % 3
    threshold = 140 + n * 4
    margins = [2 + n % 4, 4 + n % 5, 6 + n % 6]
    sums = [0, 0, 0]
    weighted_total = 0
    alerts = 0
    region = first_region
    p = price
    u = units
    for _ in range(rows):
        revenue = p * u
        sums[region] += revenue
        weighted_total += revenue * margins[region]
        alerts += 1 if threshold < revenue else 0
        region = (region + 1) % 3
        p += price_step
        u += unit_step
    program = lines(
        f"margin0 = {margins[0]}",
        f"margin1 = {margins[1]}",
        f"margin2 = {margins[2]}",
        f"threshold = {threshold}",
        "def margin(region):",
        "    value = mul(eq(region, 0), margin0)",
        "    value = add(value, mul(eq(region, 1), margin1))",
        "    value = add(value, mul(eq(region, 2), margin2))",
        "    return value",
        f"region = {first_region}",
        f"price = {price}",
        f"units = {units}",
        f"price_step = {price_step}",
        f"unit_step = {unit_step}",
        f"remaining = {rows}",
        "sum0 = 0",
        "sum1 = 0",
        "sum2 = 0",
        "weighted_total = 0",
        "alerts = 0",
        "while remaining:",
        "    revenue = mul(price, units)",
        "    sum0 = add(sum0, mul(eq(region, 0), revenue))",
        "    sum1 = add(sum1, mul(eq(region, 1), revenue))",
        "    sum2 = add(sum2, mul(eq(region, 2), revenue))",
        "    weighted_total = add(weighted_total, mul(revenue, margin(region)))",
        "    alerts = add(alerts, lt(threshold, revenue))",
        "    region = add(region, 1)",
        "    region = sub(region, mul(eq(region, 3), 3))",
        "    price = add(price, price_step)",
        "    units = add(units, unit_step)",
        "    remaining = sub(remaining, 1)",
        "print(sum0)",
        "print(sum1)",
        "print(sum2)",
        "print(weighted_total)",
        "print(alerts)",
    )
    return mk(case_id, band, "mini_dataframe_groupby_join_filter", 5, program, [*sums, weighted_total, alerts],
        f"Implement a mini pandas pipeline in MVPy: {rows} sales rows cycle region from {first_region}; price starts {price} step {price_step}; units start {units} step {unit_step}; region margins are {margins}; flag revenue above {threshold}. Print groupby revenue for regions 0/1/2, weighted total, and alert count.",
        ["pandas", "groupby", "join", "filter", "def", "while", "eq", "lt", "print"])


def cc_trace_rollup(case_id: str, band: str, n: int) -> Case:
    events = 8 + n % 9
    prompt_start = 500 + n * 13
    output_start = 80 + n * 5
    cache_start = 200 + n * 7
    tool_every = 3
    sub_every = 5
    in_rate = 2 + n % 4
    out_rate = 7 + n % 5
    cache_rate = 1 + n % 3
    totals = {"gross": 0, "cache": 0, "net": 0, "tools": 0, "subs": 0}
    for i in range(events):
        prompt = prompt_start + i * 11
        output = output_start + i * 3
        cache = cache_start + i * 5
        gross = prompt * in_rate + output * out_rate
        credit = cache * cache_rate
        totals["gross"] += gross
        totals["cache"] += credit
        totals["net"] += gross - credit
        totals["tools"] += 1 if i % tool_every == 0 else 0
        totals["subs"] += 1 if i % sub_every == 0 else 0
    program = lines(
        f"events = {events}",
        f"prompt = {prompt_start}",
        f"output = {output_start}",
        f"cache = {cache_start}",
        f"input_rate = {in_rate}",
        f"output_rate = {out_rate}",
        f"cache_rate = {cache_rate}",
        "gross_total = 0",
        "cache_total = 0",
        "net_total = 0",
        "tool_count = 0",
        "subagent_count = 0",
        "tool_phase = 0",
        "subagent_phase = 0",
        "i = 0",
        "while lt(i, events):",
        "    gross = add(mul(prompt, input_rate), mul(output, output_rate))",
        "    credit = mul(cache, cache_rate)",
        "    gross_total = add(gross_total, gross)",
        "    cache_total = add(cache_total, credit)",
        "    net_total = add(net_total, sub(gross, credit))",
        "    tool_count = add(tool_count, eq(tool_phase, 0))",
        "    subagent_count = add(subagent_count, eq(subagent_phase, 0))",
        "    tool_phase = add(tool_phase, 1)",
        "    tool_phase = sub(tool_phase, mul(eq(tool_phase, 3), 3))",
        "    subagent_phase = add(subagent_phase, 1)",
        "    subagent_phase = sub(subagent_phase, mul(eq(subagent_phase, 5), 5))",
        "    prompt = add(prompt, 11)",
        "    output = add(output, 3)",
        "    cache = add(cache, 5)",
        "    i = add(i, 1)",
        "print(gross_total)",
        "print(cache_total)",
        "print(net_total)",
        "print(tool_count)",
        "print(subagent_count)",
    )
    return mk(case_id, band, "cc_retrospect_trace_rollup", 5, program,
        [totals["gross"], totals["cache"], totals["net"], totals["tools"], totals["subs"]],
        f"Build a cc-retrospect-style trace rollup for {events} events. Prompt/output/cache token streams start at {prompt_start}/{output_start}/{cache_start}; rates are {in_rate}/{out_rate}/{cache_rate}; tool events happen at indices 0,3,6 and subagents at 0,5. Print gross, cache credit, net, tool count, subagent count.",
        ["cc-retrospect", "tokens", "trace", "while", "eq", "add", "sub", "mul", "print"])


def rolling_anomaly_dashboard(case_id: str, band: str, n: int) -> Case:
    count = 10 + n % 8
    start = 40 + n * 3
    step = 4 + n % 7
    threshold = start * 3 + step * 5
    values = [start + i * step for i in range(count)]
    windows = [values[i - 2] + values[i - 1] + values[i] for i in range(2, count)]
    total = sum(windows)
    max_window = max(windows)
    alerts = sum(1 for w in windows if threshold < w)
    program = lines(
        "def readings():",
        f"    value = {start}",
        f"    step = {step}",
        f"    remaining = {count}",
        "    while remaining:",
        "        yield value",
        "        value = add(value, step)",
        "        remaining = sub(remaining, 1)",
        f"threshold = {threshold}",
        "stream = readings()",
        "a = next(stream)",
        "b = next(stream)",
        f"remaining = {count - 2}",
        "total = 0",
        "max_window = 0",
        "alerts = 0",
        "while remaining:",
        "    c = next(stream)",
        "    window = add(add(a, b), c)",
        "    total = add(total, window)",
        "    replace = lt(max_window, window)",
        "    max_window = add(mul(replace, window), mul(sub(1, replace), max_window))",
        "    alerts = add(alerts, lt(threshold, window))",
        "    a = b",
        "    b = c",
        "    remaining = sub(remaining, 1)",
        "print(total)",
        "print(max_window)",
        "print(alerts)",
    )
    return mk(case_id, band, "rolling_anomaly_dashboard", 5, program, [total, max_window, alerts],
        f"Implement a rolling telemetry dashboard. {count} readings start at {start}, step {step}; compute every 3-reading window, threshold {threshold}. Print sum of windows, max window, and alert count.",
        ["pandas", "rolling", "anomaly", "generator", "while", "branchless_select", "lt", "print"])


def stdlib_counter_accumulate(case_id: str, band: str, n: int) -> Case:
    rows = 12 + n % 10
    start_status = n % 4
    severity_step = 1 + n % 3
    counts = [0, 0, 0, 0]
    weighted = 0
    status = start_status
    severity = 10 + n
    for _ in range(rows):
        counts[status] += 1
        weighted += severity * (status + 1)
        status = (status + severity_step) % 4
        severity += 2
    program = lines(
        f"rows = {rows}",
        f"status = {start_status}",
        f"severity = {10 + n}",
        f"severity_step = {severity_step}",
        "c0 = 0",
        "c1 = 0",
        "c2 = 0",
        "c3 = 0",
        "weighted = 0",
        "while rows:",
        "    c0 = add(c0, eq(status, 0))",
        "    c1 = add(c1, eq(status, 1))",
        "    c2 = add(c2, eq(status, 2))",
        "    c3 = add(c3, eq(status, 3))",
        "    weighted = add(weighted, mul(severity, add(status, 1)))",
        "    status = add(status, severity_step)",
        "    status = sub(status, mul(lt(3, status), 4))",
        "    severity = add(severity, 2)",
        "    rows = sub(rows, 1)",
        "print(c0)",
        "print(c1)",
        "print(c2)",
        "print(c3)",
        "print(weighted)",
    )
    return mk(case_id, band, "stdlib_counter_accumulate", 5, program, [*counts, weighted],
        f"Implement a tiny stdlib Counter plus accumulate pass. {rows} log records start status {start_status}; status advances by {severity_step} modulo 4; severity starts {10 + n} and increases by 2. Print counts for statuses 0-3 and weighted severity total.",
        ["stdlib", "counter", "accumulate", "eq", "lt", "while", "weighted_sum", "print"])


def mk(case_id: str, band: str, category: str, difficulty: int, program: str, outputs: list[int | str], prompt: str, features: list[str]) -> Case:
    return Case(case_id, band, category, difficulty, prompt, program, "".join(f"{x}\n" for x in outputs), features)


def dataset_row(case: Case, digest: str, mvpy: Path) -> dict:
    return {
        "id": case.id,
        "split": "ood",
        "difficulty_band": case.band,
        "category": case.category,
        "difficulty": case.difficulty,
        "prompt_raw": case.prompt,
        "prompt_teacher": None,
        "teacher_status": "not_requested",
        "prompt_text": (
            "<start_of_turn>developer\n"
            "You write only MVPy v0.1 programs. Use integer literals, names, positional calls, "
            "assignment, def, nonlocal, return, raise, bare try/except, while, yield, and builtins "
            "print/add/sub/mul/eq/lt/next. Return a complete runnable program.\n"
            "<end_of_turn>\n"
            "<start_of_turn>user\n"
            f"{case.prompt}\n"
            "<end_of_turn>\n"
            "<start_of_turn>model\n"
        ),
        "target_text": case.program,
        "target_qwen_text": case.program,
        "target_format": "raw_mvpy",
        "mvpy": case.program,
        "stdout": case.stdout,
        "features": case.features,
        "program_sha256": digest,
        "verifier": {
            "name": "mvpy",
            "commit": PINNED_MVPY_COMMIT,
            "binary": str(mvpy),
            "sha256": hashlib.sha256(mvpy.read_bytes()).hexdigest(),
            "exit": 0,
        },
    }


def validate(case: Case, mvpy: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="mvpy_ood_") as td:
        src = Path(td) / f"{case.id}.mvpy"
        src.write_text(case.program, encoding="utf-8")
        proc = subprocess.run([str(mvpy), str(src)], capture_output=True, text=True, timeout=5)
        if proc.returncode != 0 or proc.stdout != case.stdout:
            raise SystemExit(
                f"validation failed {case.id}: rc={proc.returncode} stdout={proc.stdout!r} "
                f"want={case.stdout!r} stderr={proc.stderr!r}"
            )


def load_seen_hashes(seen_dir: Path) -> set[str]:
    hashes: set[str] = set()
    for name in ["train_qwen.jsonl", "val_qwen.jsonl", "analysis_qwen.jsonl"]:
        path = seen_dir / name
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        hashes.add(json.loads(line)["program_sha256"])
    return hashes


def find_mvpy(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path(os.environ["MVPY_BIN"]) if os.environ.get("MVPY_BIN") else None,
        Path("/tmp/mvpy-v0.1"),
        Path("/Users/srinivasvaddi/Projects/mvpy/mvpy"),
        Path(shutil.which("mvpy")) if shutil.which("mvpy") else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    raise SystemExit("MVPY_BIN not set and no mvpy binary found")


def lines(*items: str) -> str:
    return "\n".join(items) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
