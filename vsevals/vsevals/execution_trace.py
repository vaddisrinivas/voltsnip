"""Execution tracing for dynamic tour generation.

Instead of hardcoded line numbers, track actual execution flow:
- Decorators record function entry/exit with source location
- ExecutionTrace flows through the pipeline
- tour_generator reads the trace to build tours dynamically
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class ExecutionStep:
    """A single execution point in the harness."""

    function_name: str
    file_path: str
    line_number: int
    timestamp: datetime
    duration_ms: Optional[int] = None
    decision_point: Optional[str] = None  # e.g., "retrieval_fork: TAKEN", "mode_fork: AGENT"
    context: dict[str, Any] = field(default_factory=dict)  # arbitrary context for this step


@dataclass
class ExecutionTrace:
    """Record of all execution points during a cell run."""

    task_id: str
    variant_id: str
    model_name: str
    steps: list[ExecutionStep] = field(default_factory=list)

    def record(
        self,
        function_name: str,
        file_path: str,
        line_number: int,
        decision_point: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record an execution step."""
        self.steps.append(
            ExecutionStep(
                function_name=function_name,
                file_path=file_path,
                line_number=line_number,
                timestamp=datetime.now(),
                decision_point=decision_point,
                context=context or {},
            )
        )

    def get_file_lines(self, file_path: str) -> dict[str, list[int]]:
        """Group line numbers by function for a file."""
        result: dict[str, list[int]] = {}
        for step in self.steps:
            if step.file_path == file_path:
                if step.function_name not in result:
                    result[step.function_name] = []
                result[step.function_name].append(step.line_number)
        return result


# Thread-local or context-aware trace storage
_current_trace: ExecutionTrace | None = None


def set_current_trace(trace: ExecutionTrace) -> None:
    """Set the active trace for the current execution context."""
    global _current_trace
    _current_trace = trace


def get_current_trace() -> ExecutionTrace | None:
    """Get the active trace, if any."""
    return _current_trace


def trace_execution(
    decision_point: Optional[str] = None,
    context_builder: Optional[Callable[..., dict[str, Any]]] = None,
) -> Callable[[F], F]:
    """Decorator to trace function execution.

    Args:
        decision_point: Human-readable label (e.g., "retrieval_fork: TAKEN")
        context_builder: Function to extract context from the decorated function's args/kwargs
    """

    def decorator(func: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace = get_current_trace()
            if trace is None:
                # No tracing active, just call the function
                return func(*args, **kwargs)

            # Get source location
            source_file = inspect.getsourcefile(func) or "unknown"
            source_lines = inspect.getsourcelines(func)
            source_line = source_lines[1] if source_lines else 0

            # Build context if builder provided
            context = {}
            if context_builder:
                try:
                    context = context_builder(*args, **kwargs)
                except Exception:
                    pass  # Silently skip context on error

            # Record entry
            trace.record(
                function_name=func.__name__,
                file_path=source_file,
                line_number=source_line,
                decision_point=decision_point,
                context=context,
            )

            # Call the function
            result = func(*args, **kwargs)
            return result

        return wrapper  # type: ignore

    return decorator
