"""Ansible callback plugin that writes structured events for the OVE TUI.

Reads from environment:
  OVE_LAB_NAME  — lab identifier (e.g. "libvirt-appliance")
  OVE_STATE_DIR — path to state directory for this lab

Writes:
  status.json   — atomic snapshot of current state (play, task, counters)
  events.jsonl  — append-only structured event stream
"""

from __future__ import annotations

import json
import os
import tempfile
import time

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = """
    name: ove_tui
    type: notification
    short_description: Writes structured events for the OVE Lab Manager TUI
    description:
      - Writes play/task events to a state directory as JSON for consumption
        by the OVE TUI dashboard.
    requirements:
      - OVE_LAB_NAME and OVE_STATE_DIR environment variables
"""


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "ove_tui"
    CALLBACK_NEEDS_ENABLED = False

    def __init__(self):
        super().__init__()
        self.lab_name = os.environ.get("OVE_LAB_NAME", "")
        self.state_dir = os.environ.get("OVE_STATE_DIR", "")
        self.disabled = not (self.lab_name and self.state_dir)
        if self.disabled:
            return

        os.makedirs(self.state_dir, exist_ok=True)
        self._status = {
            "lab": self.lab_name,
            "state": "running",
            "action": os.environ.get("OVE_ACTION", "deploy"),
            "phase": "",
            "current_task": "",
            "current_role": "",
            "started_at": time.time(),
            "updated_at": time.time(),
            "counters": {"ok": 0, "changed": 0, "failed": 0, "skipped": 0, "unreachable": 0},
            "pid": os.getpid(),
        }
        self._write_status()

    # -- helpers --

    def _write_status(self):
        if self.disabled:
            return
        self._status["updated_at"] = time.time()
        path = os.path.join(self.state_dir, "status.json")
        try:
            fd, tmp = tempfile.mkstemp(dir=self.state_dir, suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self._status, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def _append_event(self, event_type, **fields):
        if self.disabled:
            return
        event = {"ts": time.time(), "lab": self.lab_name, "event": event_type}
        event.update(fields)
        path = os.path.join(self.state_dir, "events.jsonl")
        try:
            with open(path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except OSError:
            pass

    def _extract_role(self, task):
        """Extract role name from a task, if any."""
        if task and hasattr(task, "_role") and task._role:
            return task._role.get_name()
        return ""

    # -- play events --

    def v2_playbook_on_play_start(self, play):
        if self.disabled:
            return
        name = play.get_name() or "(unnamed play)"
        self._status["phase"] = name
        self._status["current_task"] = ""
        self._status["current_role"] = ""
        self._write_status()
        self._append_event("play_start", play=name)

    # -- task events --

    def v2_playbook_on_task_start(self, task, is_conditional):
        if self.disabled:
            return
        name = task.get_name() or "(unnamed task)"
        role = self._extract_role(task)
        self._status["current_task"] = name
        self._status["current_role"] = role
        self._write_status()
        self._append_event("task_start", task=name, role=role)

    def v2_runner_on_ok(self, result, **kwargs):
        if self.disabled:
            return
        changed = result._result.get("changed", False)
        key = "changed" if changed else "ok"
        self._status["counters"][key] += 1
        self._write_status()
        host = result._host.get_name() if result._host else "unknown"
        self._append_event("task_ok", host=host, changed=changed,
                           task=self._status["current_task"])

    def v2_runner_on_failed(self, result, ignore_errors=False, **kwargs):
        if self.disabled:
            return
        self._status["counters"]["failed"] += 1
        self._write_status()
        host = result._host.get_name() if result._host else "unknown"
        msg = result._result.get("msg", "")
        self._append_event("task_failed", host=host, task=self._status["current_task"],
                           msg=msg, ignore_errors=ignore_errors)

    def v2_runner_on_skipped(self, result, **kwargs):
        if self.disabled:
            return
        self._status["counters"]["skipped"] += 1
        self._write_status()
        host = result._host.get_name() if result._host else "unknown"
        self._append_event("task_skipped", host=host, task=self._status["current_task"])

    def v2_runner_on_unreachable(self, result, **kwargs):
        if self.disabled:
            return
        self._status["counters"]["unreachable"] += 1
        self._write_status()
        host = result._host.get_name() if result._host else "unknown"
        msg = result._result.get("msg", "")
        self._append_event("task_unreachable", host=host, task=self._status["current_task"],
                           msg=msg)

    # -- playbook end --

    def v2_playbook_on_stats(self, stats):
        if self.disabled:
            return
        failed = self._status["counters"]["failed"]
        unreachable = self._status["counters"]["unreachable"]
        self._status["state"] = "failed" if (failed or unreachable) else "completed"
        self._status["phase"] = "done"
        self._status["current_task"] = ""
        self._write_status()
        self._append_event("playbook_stats", state=self._status["state"],
                           counters=self._status["counters"])
