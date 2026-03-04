"""Tests for vsevals.exporters.concurrency — ProviderThrottle."""

from __future__ import annotations

import threading
import time

import pytest

from vsevals.exporters.concurrency import ProviderThrottle


# ---------------------------------------------------------------------------
# Basic acquire / release
# ---------------------------------------------------------------------------


def test_throttle_acquire_release():
    throttle = ProviderThrottle(limits={"openai": 2}, stagger_ms=0)
    throttle.acquire("openai")
    throttle.release("openai")


def test_throttle_unknown_provider():
    throttle = ProviderThrottle(limits={"openai": 2}, stagger_ms=0)
    # Should not raise for unknown provider
    throttle.acquire("unknown")
    throttle.release("unknown")


# ---------------------------------------------------------------------------
# Concurrency limiting
# ---------------------------------------------------------------------------


def test_throttle_concurrency_limit():
    throttle = ProviderThrottle(limits={"openai": 1}, stagger_ms=0)
    acquired = []
    barrier = threading.Event()

    def worker(name):
        throttle.acquire("openai")
        acquired.append(name)
        barrier.wait(timeout=2)
        throttle.release("openai")

    t1 = threading.Thread(target=worker, args=("t1",))
    t2 = threading.Thread(target=worker, args=("t2",))
    t1.start()
    time.sleep(0.05)  # Give t1 time to acquire
    t2.start()
    time.sleep(0.05)

    # Only one should have acquired with limit=1
    assert len(acquired) == 1

    barrier.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert len(acquired) == 2


# ---------------------------------------------------------------------------
# Stagger timing
# ---------------------------------------------------------------------------


def test_throttle_stagger():
    throttle = ProviderThrottle(limits={"p": 2}, stagger_ms=100)
    t0 = time.monotonic()
    throttle.acquire("p")
    throttle.release("p")
    throttle.acquire("p")
    elapsed = (time.monotonic() - t0) * 1000
    throttle.release("p")
    # Second acquire should wait ~100ms
    assert elapsed >= 80  # allow some tolerance


# ---------------------------------------------------------------------------
# Multiple providers independent
# ---------------------------------------------------------------------------


def test_throttle_multiple_providers():
    throttle = ProviderThrottle(limits={"openai": 1, "anthropic": 1}, stagger_ms=0)
    results = []

    def worker(provider):
        throttle.acquire(provider)
        results.append(provider)
        time.sleep(0.05)
        throttle.release(provider)

    t1 = threading.Thread(target=worker, args=("openai",))
    t2 = threading.Thread(target=worker, args=("anthropic",))
    t1.start()
    t2.start()
    t1.join(timeout=2)
    t2.join(timeout=2)
    # Both should complete (different providers → independent)
    assert set(results) == {"openai", "anthropic"}
