"""OVE Lab Manager TUI — manage and monitor parallel lab deployments."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import yaml
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, RichLog, Static

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LABS_DIR = PROJECT_ROOT / "labs"
STATE_ROOT = PROJECT_ROOT / ".ove-demo-cache" / "tui"
CALLBACK_DIR = PROJECT_ROOT / "callback_plugins"

PLAYBOOKS = {
    "deploy": "site.yml",
    "teardown": "teardown.yml",
    "reset": "reset-ove-nodes.yml",
}

# Phase ordering per (backend, install_method) for progress estimation.
PHASE_ORDER: dict[tuple[str, str], list[str]] = {
    ("openstack", "ove"): [
        "Validate inputs",
        "Create OVE demo infrastructure (OpenStack)",
        "Configure bastion host",
        "Create OVE nodes (OpenStack)",
    ],
    ("openstack", "appliance"): [
        "Validate inputs",
        "Create OVE demo infrastructure (OpenStack)",
        "Configure bastion host",
        "Build appliance image on bastion",
        "Create OVE nodes (OpenStack)",
    ],
    ("libvirt", "ove"): [
        "Validate inputs",
        "Prepare KVM host and create bastion VM (libvirt)",
        "Configure bastion host",
        "Create OVE nodes (libvirt)",
        "Deploy sushy-emulator on KVM host (libvirt)",
    ],
    ("libvirt", "appliance"): [
        "Validate inputs",
        "Prepare KVM host and create bastion VM (libvirt)",
        "Configure bastion host",
        "Build appliance image on bastion",
        "Create OVE nodes (libvirt)",
        "Deploy sushy-emulator on KVM host (libvirt)",
    ],
}


# ---------------------------------------------------------------------------
# Lab discovery and state
# ---------------------------------------------------------------------------


def discover_labs() -> list[dict]:
    """Discover labs from labs/*.yml files and merge any existing state."""
    labs = []
    if not LABS_DIR.is_dir():
        return labs

    for lab_file in sorted(LABS_DIR.glob("*.yml")):
        name = lab_file.stem
        try:
            with open(lab_file) as f:
                cfg = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            cfg = {}

        lab = {
            "name": name,
            "file": str(lab_file),
            "backend": cfg.get("infra_backend", "openstack"),
            "method": cfg.get("install_method", "ove"),
            "lab_id": cfg.get("lab_id", 0),
            # state fields — overwritten by load_status if available
            "state": "idle",
            "action": "",
            "phase": "",
            "current_task": "",
            "current_role": "",
            "started_at": 0,
            "updated_at": 0,
            "counters": {"ok": 0, "changed": 0, "failed": 0, "skipped": 0, "unreachable": 0},
            "pid": 0,
        }
        lab.update(load_status(name))
        labs.append(lab)

    return labs


def load_status(lab_name: str) -> dict:
    """Load status.json for a lab, validating PID liveness."""
    status_path = STATE_ROOT / lab_name / "status.json"
    if not status_path.is_file():
        return {}
    try:
        with open(status_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # Validate PID if state claims running
    if data.get("state") == "running":
        pid = data.get("pid", 0)
        if pid and not _pid_alive(pid):
            data["state"] = "failed"
            data["phase"] = "crashed"
            # Persist corrected state
            try:
                with open(status_path, "w") as f:
                    json.dump(data, f)
            except OSError:
                pass

    return data


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def format_elapsed(started: float) -> str:
    if not started:
        return ""
    elapsed = int(time.time() - started)
    if elapsed < 0:
        return ""
    m, s = divmod(elapsed, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def phase_progress(lab: dict) -> str:
    """Return a progress string like '3/6' based on known phase ordering."""
    key = (lab["backend"], lab["method"])
    phases = PHASE_ORDER.get(key)
    if not phases or not lab.get("phase"):
        return ""
    phase = lab["phase"]
    if phase == "done":
        return f"{len(phases)}/{len(phases)}"
    for i, p in enumerate(phases):
        if phase.startswith(p) or p.startswith(phase):
            return f"{i + 1}/{len(phases)}"
    return ""


# ---------------------------------------------------------------------------
# State symbols
# ---------------------------------------------------------------------------

STATE_DISPLAY = {
    "idle": ("idle", "dim white"),
    "running": ("running", "green"),
    "completed": ("done", "bold green"),
    "failed": ("FAILED", "bold red"),
}


# ---------------------------------------------------------------------------
# TUI Widgets
# ---------------------------------------------------------------------------


class LabStatusBar(Static):
    """Top-line summary bar."""

    def update_summary(self, labs: list[dict]) -> None:
        running = sum(1 for l in labs if l["state"] == "running")
        failed = sum(1 for l in labs if l["state"] == "failed")
        total = len(labs)
        parts = [f"[bold]{total}[/] labs"]
        if running:
            parts.append(f"[green]{running} running[/]")
        if failed:
            parts.append(f"[red]{failed} failed[/]")
        self.update(" | ".join(parts))


class ConfirmBar(Static):
    """Inline confirmation prompt."""

    def ask(self, message: str) -> None:
        self.update(f"[bold yellow]{message}[/]  [dim]y/n[/]")
        self.display = True

    def hide(self) -> None:
        self.update("")
        self.display = False


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------


class OveLabManager(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #lab-table {
        height: 1fr;
        min-height: 6;
        max-height: 14;
    }
    #confirm-bar {
        height: 1;
        display: none;
        padding: 0 1;
        background: $warning-darken-2;
    }
    #log-view {
        height: 3fr;
        border-top: solid $primary;
    }
    #log-header {
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "deploy", "Deploy"),
        Binding("t", "teardown", "Teardown"),
        Binding("r", "reset", "Reset"),
        Binding("a", "deploy_all", "Deploy All"),
        Binding("x", "cancel", "Cancel"),
        Binding("enter", "toggle_log", "View Logs", priority=True),
        Binding("l", "next_log", "Next Log"),
        Binding("y", "confirm_yes", "Yes", show=False),
        Binding("n", "confirm_no", "No", show=False),
    ]

    TITLE = "OVE Lab Manager"

    # -- state --
    labs: reactive[list[dict]] = reactive(list, init=False)
    selected_lab: reactive[str] = reactive("", init=False)
    log_lab: reactive[str] = reactive("", init=False)
    _pending_action: str = ""
    _pending_targets: list[str] = []
    _log_tasks: dict[str, asyncio.Task] = {}

    def compose(self):
        yield Header()
        yield LabStatusBar(id="status-bar")
        yield DataTable(id="lab-table", cursor_type="row")
        yield ConfirmBar(id="confirm-bar")
        yield Static("", id="log-header")
        yield RichLog(id="log-view", highlight=True, markup=True, wrap=True, max_lines=2000)
        yield Footer()

    def on_mount(self) -> None:
        self.labs = discover_labs()

        table = self.query_one("#lab-table", DataTable)
        table.add_columns("Lab", "Backend", "Method", "State", "Progress", "Phase", "Task", "Time")
        self._refresh_table()

        if self.labs:
            self.selected_lab = self.labs[0]["name"]
            self.log_lab = self.labs[0]["name"]

        self.set_interval(1.0, self._poll_status)
        self._start_log_tailers()

    # -- table rendering --

    def _refresh_table(self) -> None:
        table = self.query_one("#lab-table", DataTable)

        # Preserve cursor position across refresh
        saved_cursor = table.cursor_row

        table.clear()
        for lab in self.labs:
            label, style = STATE_DISPLAY.get(lab["state"], ("?", "white"))
            progress = phase_progress(lab)
            phase = lab.get("phase", "") or ""
            # Truncate long phase names
            if len(phase) > 30:
                phase = phase[:27] + "..."
            task = lab.get("current_task", "") or ""
            if len(task) > 35:
                task = task[:32] + "..."
            elapsed = format_elapsed(lab.get("started_at", 0)) if lab["state"] == "running" else ""
            action_prefix = f"[dim]{lab.get('action', '')}[/] " if lab.get("action") and lab["state"] == "running" else ""
            table.add_row(
                lab["name"],
                lab["backend"],
                lab["method"],
                f"[{style}]{action_prefix}{label}[/]",
                progress,
                phase,
                task,
                elapsed,
            )

        # Restore cursor position
        if saved_cursor is not None and 0 <= saved_cursor < table.row_count:
            table.move_cursor(row=saved_cursor)

        self.query_one("#status-bar", LabStatusBar).update_summary(self.labs)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None and 0 <= event.cursor_row < len(self.labs):
            self.selected_lab = self.labs[event.cursor_row]["name"]

    # -- status polling --

    def _poll_status(self) -> None:
        changed = False
        for lab in self.labs:
            old_state = lab["state"]
            new_data = load_status(lab["name"])
            if new_data:
                lab.update(new_data)
            if lab["state"] != old_state:
                changed = True
        # Always refresh to update elapsed time
        self._refresh_table()
        self._update_log_header()

    # -- log tailing --

    def _start_log_tailers(self) -> None:
        for lab in self.labs:
            self._ensure_log_tailer(lab["name"])

    def _ensure_log_tailer(self, lab_name: str) -> None:
        if lab_name not in self._log_tasks or self._log_tasks[lab_name].done():
            self._log_tasks[lab_name] = asyncio.create_task(self._tail_log(lab_name))

    def _cancel_log_tailers(self) -> None:
        for task in self._log_tasks.values():
            task.cancel()
        self._log_tasks.clear()

    async def _tail_log(self, lab_name: str) -> None:
        """Tail ansible.log for a lab, appending lines to the log view when selected."""
        log_path = STATE_ROOT / lab_name / "ansible.log"
        pos = 0
        try:
            while True:
                try:
                    if log_path.is_file():
                        size = log_path.stat().st_size
                        if size > pos:
                            with open(log_path) as f:
                                f.seek(pos)
                                new_data = f.read()
                                pos = f.tell()
                            if new_data and self.log_lab == lab_name:
                                log_view = self.query_one("#log-view", RichLog)
                                for line in new_data.splitlines():
                                    log_view.write(line)
                except OSError:
                    pass
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    def _update_log_header(self) -> None:
        lab = self._get_lab(self.log_lab)
        if lab:
            label, style = STATE_DISPLAY.get(lab["state"], ("?", "white"))
            header = f"[bold]Logs:[/] {lab['name']}  [{style}]{label}[/]"
            if lab.get("action"):
                header += f"  [dim]({lab['action']})[/]"
        else:
            header = "[dim]No lab selected[/]"
        self.query_one("#log-header", Static).update(header)

    def _switch_log(self, lab_name: str) -> None:
        """Switch the log panel to show a different lab."""
        self.log_lab = lab_name
        log_view = self.query_one("#log-view", RichLog)
        log_view.clear()
        # Load existing log content
        log_path = STATE_ROOT / lab_name / "ansible.log"
        if log_path.is_file():
            try:
                content = log_path.read_text()
                for line in content.splitlines()[-200:]:  # Show last 200 lines
                    log_view.write(line)
            except OSError:
                pass
        # Reset tailer position to current end so we only get new content
        self._ensure_log_tailer(lab_name)
        self._update_log_header()

    # -- lifecycle --

    def action_quit(self) -> None:
        self._cancel_log_tailers()
        self.exit()

    # -- helpers --

    def _get_lab(self, name: str) -> dict | None:
        for lab in self.labs:
            if lab["name"] == name:
                return lab
        return None

    # -- actions --

    def action_toggle_log(self) -> None:
        if self.selected_lab and self.selected_lab != self.log_lab:
            self._switch_log(self.selected_lab)

    def action_next_log(self) -> None:
        if not self.labs:
            return
        names = [l["name"] for l in self.labs]
        try:
            idx = names.index(self.log_lab)
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(names)
        self._switch_log(names[next_idx])

    def action_deploy(self) -> None:
        self._request_action("deploy", [self.selected_lab])

    def action_teardown(self) -> None:
        self._request_action("teardown", [self.selected_lab])

    def action_reset(self) -> None:
        self._request_action("reset", [self.selected_lab])

    def action_deploy_all(self) -> None:
        idle_labs = [l["name"] for l in self.labs if l["state"] in ("idle", "completed", "failed")]
        if idle_labs:
            self._request_action("deploy", idle_labs)

    def action_cancel(self) -> None:
        lab = self._get_lab(self.selected_lab)
        if lab and lab["state"] == "running" and lab.get("pid"):
            self._pending_action = "cancel"
            self._pending_targets = [self.selected_lab]
            self.query_one("#confirm-bar", ConfirmBar).ask(
                f"Cancel {lab.get('action', 'action')} on {self.selected_lab}?"
            )

    def _request_action(self, action: str, targets: list[str]) -> None:
        if not targets:
            return

        # Block if any target is already running
        for name in targets:
            lab = self._get_lab(name)
            if lab and lab["state"] == "running":
                self.notify(f"{name} is already running", severity="warning")
                return

        # Teardown and reset need confirmation
        if action in ("teardown", "reset"):
            names = ", ".join(targets)
            label = "Teardown" if action == "teardown" else "Reset nodes on"
            self._pending_action = action
            self._pending_targets = targets
            self.query_one("#confirm-bar", ConfirmBar).ask(f"{label} {names}?")
            return

        # Deploy — go ahead
        self._run_action(action, targets)

    def action_confirm_yes(self) -> None:
        confirm = self.query_one("#confirm-bar", ConfirmBar)
        if not confirm.display:
            return
        confirm.hide()
        if self._pending_action == "cancel":
            for name in self._pending_targets:
                self._cancel_lab(name)
        else:
            self._run_action(self._pending_action, self._pending_targets)
        self._pending_action = ""
        self._pending_targets = []

    def action_confirm_no(self) -> None:
        self.query_one("#confirm-bar", ConfirmBar).hide()
        self._pending_action = ""
        self._pending_targets = []

    def _cancel_lab(self, lab_name: str) -> None:
        lab = self._get_lab(lab_name)
        if not lab or not lab.get("pid"):
            return
        pid = lab["pid"]
        try:
            # Send SIGTERM to process group to kill ansible + children
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            self.notify(f"Sent SIGTERM to {lab_name} (pid {pid})")
        except (OSError, ProcessLookupError):
            self.notify(f"Process {pid} already gone", severity="warning")

    def _run_action(self, action: str, targets: list[str]) -> None:
        for lab_name in targets:
            self._spawn_ansible(action, lab_name)
        # Switch log to the first target
        if targets:
            self._switch_log(targets[0])

    @work(thread=True)
    def _spawn_ansible(self, action: str, lab_name: str) -> None:
        """Spawn ansible-playbook for a lab in a background thread."""
        lab = self._get_lab(lab_name)
        if not lab:
            return

        playbook = PLAYBOOKS.get(action)
        if not playbook:
            return

        state_dir = STATE_ROOT / lab_name
        state_dir.mkdir(parents=True, exist_ok=True)

        # Clear old events and log for a fresh run
        for fname in ("events.jsonl", "ansible.log"):
            p = state_dir / fname
            if p.exists():
                p.unlink()

        playbook_path = PROJECT_ROOT / playbook
        lab_file = lab["file"]

        env = os.environ.copy()
        env["OVE_LAB_NAME"] = lab_name
        env["OVE_STATE_DIR"] = str(state_dir)
        env["OVE_ACTION"] = action
        env["ANSIBLE_CALLBACK_PLUGINS"] = str(CALLBACK_DIR)
        env["ANSIBLE_CALLBACKS_ENABLED"] = "ove_tui"

        log_path = state_dir / "ansible.log"

        self.call_from_thread(
            self.notify, f"Starting {action} on {lab_name}"
        )

        log_file = open(log_path, "w")
        try:
            proc = subprocess.Popen(
                ["ansible-playbook", str(playbook_path), f"-e@{lab_file}"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
                env=env,
                start_new_session=True,  # New process group for clean cancel
            )

            # Write PID file
            pid_path = state_dir / "pid"
            pid_path.write_text(str(proc.pid))

            # Update local lab state immediately
            lab["state"] = "running"
            lab["action"] = action
            lab["pid"] = proc.pid
            lab["started_at"] = time.time()

            # Wait for completion
            proc.wait()
        finally:
            log_file.close()

        # Reload final status from the callback plugin's output
        final = load_status(lab_name)
        if final:
            lab.update(final)

        if proc.returncode != 0 and lab["state"] != "failed":
            lab["state"] = "failed"
            status_path = state_dir / "status.json"
            try:
                with open(status_path, "w") as f:
                    json.dump({
                        "lab": lab_name,
                        "state": "failed",
                        "action": action,
                        "phase": lab.get("phase", ""),
                        "current_task": lab.get("current_task", ""),
                        "current_role": lab.get("current_role", ""),
                        "started_at": lab.get("started_at", 0),
                        "updated_at": time.time(),
                        "counters": lab.get("counters", {}),
                        "pid": 0,
                    }, f)
            except OSError:
                pass

        severity = "information" if proc.returncode == 0 else "error"
        result = "completed" if proc.returncode == 0 else "FAILED"
        self.call_from_thread(
            self.notify, f"{lab_name} {action} {result}", severity=severity
        )
