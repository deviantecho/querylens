"""Temporary uploaded shops, isolated from sample data and other browser sessions."""

import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from querylens.dataset import write_dataset
from querylens.errors import QueryError
from querylens.imports import parse_spreadsheet, status_values, validate_sheet
from querylens.service import Workbench


class UploadBudget:
    def __init__(self, capacity=8):
        self.slots = threading.BoundedSemaphore(capacity)


class UploadWorkspace:
    def __init__(self):
        self.lock = threading.RLock()
        self.pending = None
        self.prepared = None
        self.inspected_at = 0
        self.workbench = None
        self.dashboard = None
        self.directory = None
        self.budget = None
        self.plans = OrderedDict()
        self.closed = False

    def active(self, sample):
        if self.closed:
            raise QueryError("This browser session expired. Refresh the page.")
        return self.workbench or sample

    def inspect(self, body, budget):
        if self.closed:
            raise QueryError("This browser session expired. Refresh the page.")
        reserved = False
        if self.budget is None:
            if not budget.slots.acquire(blocking=False):
                raise QueryError(
                    "All eight upload workspaces are in use. Try again later or run QueryLens locally."
                )
            self.budget, reserved = budget, True
        self.pending = self.prepared = None
        try:
            self.pending = parse_spreadsheet(body)
            self.inspected_at = time.monotonic()
            return self.pending.inspection()
        except Exception:
            if reserved and self.workbench is None:
                self._release_budget()
            raise

    def validate(self, body):
        self.prepared = None
        self._pending(body.get("upload_id"))
        preview, self.prepared = validate_sheet(self.pending, body)
        return preview

    def statuses(self, body):
        self._pending(body.get("upload_id"))
        values = status_values(self.pending, body.get("column"))
        if len(values) > 50:
            raise QueryError("Use no more than 50 distinct order statuses in one sheet.")
        from querylens.imports import STATUS_DEFAULTS

        return {
            "values": [
                {"value": v, "suggested": STATUS_DEFAULTS.get(v.lower(), "")} for v in values
            ]
        }

    def _pending(self, upload_id):
        if (
            self.closed
            or not self.pending
            or self.pending.id != upload_id
            or time.monotonic() - self.inspected_at >= 900
        ):
            self.pending = self.prepared = None
            if self.workbench is None:
                self._release_budget()
            raise QueryError(
                "This upload preview expired or belongs to another session. Choose the file again."
            )

    def commit(self, body, sample):
        self._pending(body.get("upload_id"))
        if not self.prepared or body.get("preview_id") != self.prepared["info"]["id"]:
            raise QueryError("Check the column matches and preview your totals before importing.")
        root = sample.data_dir / "uploads"
        root.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="shop-", dir=root)
        try:
            path = Path(directory.name)
            write_dataset(
                path / "commerce.duckdb", self.prepared["customers"], self.prepared["orders"]
            )
            workbench = Workbench(
                path,
                seed=False,
                ai=sample.ai,
                dataset_info=self.prepared["info"],
                **sample.resource_limits,
            )
            dashboard = workbench.dashboard()
        except Exception:
            directory.cleanup()
            raise
        old_directory = self.directory
        self.directory, self.workbench, self.dashboard = directory, workbench, dashboard
        self.pending = self.prepared = None
        self.plans.clear()
        if old_directory:
            old_directory.cleanup()
        return dashboard

    def remember(self, plan):
        self.plans[plan["id"]] = plan
        while len(self.plans) > 20:
            self.plans.popitem(last=False)

    def plan(self, plan_id):
        return self.plans.get(plan_id) if isinstance(plan_id, str) else None

    def reset(self):
        self.pending = self.prepared = None
        self.workbench = self.dashboard = None
        self.plans.clear()
        if self.directory:
            self.directory.cleanup()
            self.directory = None
        self._release_budget()

    def cancel_preview(self):
        self.pending = self.prepared = None
        if self.workbench is None:
            self._release_budget()

    def _release_budget(self):
        if self.budget:
            self.budget.slots.release()
            self.budget = None

    def close(self):
        with self.lock:
            self.reset()
            self.closed = True
