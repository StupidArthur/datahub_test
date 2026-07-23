"""Core serial Case runner with per-Case resource isolation and LIFO cleanup."""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .catalog import all_defs
from .config import RunConfig
from .context import RunContext
from .events import EventEmitter
from .models import CaseDef, CaseResult, CaseStatus, RunStats, StepResult
from .report import build_report, write_report


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class CancellationToken:
    def __init__(self) -> None:
        self._evt = threading.Event()

    def cancel(self) -> None:
        self._evt.set()

    def cancelled(self) -> bool:
        return self._evt.is_set()


def _setup_file_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ua_test_harness.runner")
    logger.setLevel(logging.DEBUG)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(logging.Formatter("[runner %(levelname)s] %(message)s"))
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


class Runner:
    def __init__(
        self,
        config: RunConfig,
        *,
        cases: list | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = config
        self.emitter = EventEmitter()
        self.cases = self._normalize_cases(cases) if cases is not None else all_defs()
        self.stats = RunStats()
        self.results: list[CaseResult] = []
        self.token = CancellationToken()
        self.started_at = ""
        self.finished_at = ""
        self.logger: logging.Logger | None = None
        self._sig_installed = False

    @staticmethod
    def _normalize_cases(cases: list) -> list[CaseDef]:
        out: list[CaseDef] = []
        for candidate in cases:
            if isinstance(candidate, CaseDef):
                out.append(candidate)
            elif callable(candidate) and hasattr(candidate, "__ua_case_def__"):
                out.append(candidate.__ua_case_def__)
            else:
                raise TypeError(f"unsupported case entry: {candidate!r}")
        return out

    def run(self) -> int:
        cfg = self.config
        try:
            self.started_at = _now()
            run_dir = Path(cfg.paths.run_dir) if cfg.paths.run_dir else None
            self.logger = _setup_file_logger(
                run_dir / "runner.log" if run_dir else Path("./runner.log")
            )
            self._install_signals()
            self._emit_log(f"run started id={cfg.run_id} total={len(self.cases)}")
            self.emitter.run_started(cfg.run_id, len(self.cases))
            ctx = RunContext(
                config=cfg,
                emitter=self.emitter,
                evidence_root=run_dir,
                log_path=(run_dir / "runner.log") if run_dir else None,
                cancellation_token=self.token,
            )
            for index, case_def in enumerate(self.cases, 1):
                if self.token.cancelled():
                    self._emit_log(f"cancellation received, stop at {case_def.id}")
                    break
                self._run_one(ctx, case_def, index)

            run_cleanup_errors: list[str] = []
            run_cleanup = ctx.registry.cleanup_all(run_cleanup_errors)
            if run_cleanup == CaseStatus.CLEANUP_FAILED:
                self.stats.cleanup_failed += 1
                self._emit_log(
                    "run-level cleanup failed: " + "; ".join(run_cleanup_errors),
                    level="ERROR",
                )

            self.finished_at = _now()
            status = self._overall_status()
            self.emitter.run_finished(status, self.stats.to_dict())
            report = build_report(
                run_id=cfg.run_id,
                started_at=self.started_at,
                finished_at=self.finished_at,
                status=status,
                stats=self.stats,
                cases=self.results,
                note=cfg.note,
            )
            if cfg.paths.report_path:
                write_report(report, cfg.paths.report_path)
                self._emit_log(f"report written: {cfg.paths.report_path}")
            self._emit_log(f"run finished status={status} summary={self.stats.to_dict()}")
            if status == "CANCELLED":
                return 130
            if status in ("FAIL", "ERROR", "CLEANUP_FAILED"):
                return 1
            return 0
        except _ConfigError as exc:
            self._emit_log(f"config error: {exc}", level="ERROR")
            return 2

    def _run_one(self, ctx: RunContext, case_def: CaseDef, index: int) -> None:
        result = CaseResult(case_id=case_def.id, title=case_def.title)
        result.started_at = _now()
        self.emitter.case_started(case_def.id, index, len(self.cases))
        started = time.monotonic()
        case_status = CaseStatus.PASS
        summary = ""
        case_ctx = ctx.case_context(case_def.id, case_def.title)

        run_registry = ctx.registry
        ctx.registry = case_ctx.registry
        result.steps = [
            StepResult(
                case_id=case_def.id,
                step_id="setup",
                title="setup",
                status=CaseStatus.RUNNING,
                started_at=_now(),
            )
        ]
        try:
            outcome = case_def.impl_func(ctx, case_ctx)
            if isinstance(outcome, CaseStatus):
                case_status = outcome
            elif isinstance(outcome, str):
                case_status = CaseStatus.from_str(outcome)
            result.steps[-1].status = CaseStatus.PASS
        except _Cancelled:
            case_status = CaseStatus.CANCELLED
            summary = "cancelled"
            result.steps[-1].status = CaseStatus.CANCELLED
        except AssertionError as exc:
            case_status = CaseStatus.FAIL
            summary = f"assert: {exc}"
            result.steps[-1].status = CaseStatus.FAIL
            result.steps[-1].message = str(exc)
            self._emit_log(f"case {case_def.id} FAIL: {exc}", level="ERROR")
        except Exception as exc:
            case_status = CaseStatus.ERROR
            summary = f"error: {exc}"
            result.steps[-1].status = CaseStatus.ERROR
            result.steps[-1].message = str(exc)
            self._emit_log(
                f"case {case_def.id} ERROR: {exc}\n{traceback.format_exc()}",
                level="ERROR",
            )
        finally:
            ctx.registry = run_registry
            result.steps[-1].finished_at = _now()
            result.steps[-1].duration_ms = int((time.monotonic() - started) * 1000)

        cleanup_status, cleanup_message = self._cleanup_case(ctx, case_ctx, case_def)
        result.cleanup_status = cleanup_status
        result.cleanup_message = cleanup_message
        if cleanup_status == CaseStatus.CLEANUP_FAILED:
            self.stats.cleanup_failed += 1

        result.status = case_status
        result.finished_at = _now()
        result.duration_ms = int((time.monotonic() - started) * 1000)
        result.summary = summary or case_status.value
        self.stats.add(case_status)
        self.results.append(result)
        self.emitter.case_finished(
            case_def.id,
            result.status.value,
            result.duration_ms,
            summary=result.summary,
        )
        self.emitter.cleanup_finished(
            case_def.id,
            result.cleanup_status.value,
            message=result.cleanup_message,
        )

    def _cleanup_case(self, ctx: RunContext, case_ctx, case_def: CaseDef) -> tuple[CaseStatus, str]:
        errors: list[str] = []
        callbacks: list[Callable[[], None]] = []
        for key in (f"cleanup_{case_def.id}", f"cleanups_{case_def.id}"):
            value = ctx.bag.pop(key, None) if isinstance(ctx.bag, dict) else None
            if callable(value):
                callbacks.append(value)
            elif isinstance(value, list):
                callbacks.extend(fn for fn in value if callable(fn))
        for callback in reversed(callbacks):
            try:
                callback()
            except Exception as exc:
                errors.append(f"callback:{exc}")

        registry_status = case_ctx.registry.cleanup_all(errors)
        if errors or registry_status == CaseStatus.CLEANUP_FAILED:
            message = "; ".join(errors)
            self._emit_log(f"cleanup {case_def.id}: {message}", level="ERROR")
            return CaseStatus.CLEANUP_FAILED, message
        return CaseStatus.PASS, ""

    def _overall_status(self) -> str:
        if self.stats.failed or self.stats.errors:
            return "FAIL"
        if self.stats.cleanup_failed:
            return "CLEANUP_FAILED"
        if any(result.status == CaseStatus.CANCELLED for result in self.results):
            return "CANCELLED"
        return "FINISHED"

    def _emit_log(self, message: str, level: str = "INFO") -> None:
        if self.logger:
            getattr(self.logger, level.lower(), self.logger.info)(message)
        self.emitter.log(level, case_id=None, message=message)

    def _install_signals(self) -> None:
        if self._sig_installed:
            return
        self._sig_installed = True

        def handler(signum, _frame):
            self._emit_log(f"signal {signum} received, cancelling", level="WARN")
            self.token.cancel()

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except (ValueError, OSError):
            pass


class _ConfigError(Exception):
    pass


class _Cancelled(Exception):
    pass
