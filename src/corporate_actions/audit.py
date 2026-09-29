"""Audit trail simples: run_id, estágios com duração, validadores executados, erros e retries.

Sem infraestrutura externa. Não registra o texto do documento; apenas hashes, metadados,
resultados e os trechos mínimos de evidência que já vão no registro de saída.
"""
import datetime as dt
import time
import traceback
import uuid
from contextlib import contextmanager


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def new_run_id() -> str:
    return f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


class DocumentAudit:
    def __init__(self, run_id: str, pipeline_version: str):
        self.run_id = run_id
        self.pipeline_version = pipeline_version
        self.started_at = utc_now()
        self._t0 = time.perf_counter_ns()
        self.finished_at = None
        self.duration_us = None
        self.stages: list[dict] = []
        self.errors: list[dict] = []
        self.retries = 0

    @contextmanager
    def stage(self, name: str):
        entry = {"stage": name, "started_at": utc_now(), "status": "ok", "duration_us": None}
        t0 = time.perf_counter_ns()
        try:
            yield entry
        except Exception as exc:
            entry["status"] = "error"
            self.errors.append({"stage": name, "type": type(exc).__name__, "message": str(exc),
                                "traceback_tail": traceback.format_exc().strip().splitlines()[-3:]})
            raise
        finally:
            entry["duration_us"] = (time.perf_counter_ns() - t0) // 1000
            self.stages.append(entry)

    def skip(self, name: str, reason: str):
        self.stages.append({"stage": name, "started_at": utc_now(), "status": "skipped", "reason": reason,
                            "duration_us": 0})

    def finish(self):
        self.finished_at = utc_now()
        self.duration_us = (time.perf_counter_ns() - self._t0) // 1000

    def to_dict(self, **extra) -> dict:
        return {"run_id": self.run_id, "pipeline_version": self.pipeline_version, "started_at": self.started_at,
                "finished_at": self.finished_at, "duration_us": self.duration_us, "stages": self.stages,
                "errors": self.errors, "retries": self.retries, **extra}
