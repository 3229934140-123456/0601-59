import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class LogEntry:
    timestamp: str
    command: str
    action: str
    source: str
    target: str = ""
    status: str = "success"
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OperationLog:
    session_id: str
    start_time: str
    end_time: str = ""
    command: str = ""
    entries: List[LogEntry] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "command": self.command,
            "entries": [e.to_dict() for e in self.entries],
            "summary": self.summary,
        }


class Logger:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.log_dir = self.project_dir / ".brand-kit" / "logs"
        self.current_log: Optional[OperationLog] = None

    def _ensure_log_dir(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def start_session(self, command: str) -> str:
        self._ensure_log_dir()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_log = OperationLog(
            session_id=session_id,
            start_time=datetime.now().isoformat(),
            command=command,
            summary={"total": 0, "success": 0, "failed": 0, "skipped": 0},
        )
        return session_id

    def log_action(self, action: str, source: str, target: str = "",
                   status: str = "success", details: str = ""):
        if self.current_log is None:
            return
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            command=self.current_log.command,
            action=action,
            source=source,
            target=target,
            status=status,
            details=details,
        )
        self.current_log.entries.append(entry)
        self.current_log.summary["total"] += 1
        if status in self.current_log.summary:
            self.current_log.summary[status] += 1
        else:
            self.current_log.summary[status] = 1

    def end_session(self):
        if self.current_log is None:
            return
        self.current_log.end_time = datetime.now().isoformat()
        self._save_log()

    def _save_log(self):
        if self.current_log is None:
            return
        self._ensure_log_dir()
        log_file = self.log_dir / f"{self.current_log.session_id}_{self.current_log.command}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(self.current_log.to_dict(), f, indent=2, ensure_ascii=False)

    def get_last_session(self) -> Optional[OperationLog]:
        if not self.log_dir.exists():
            return None
        log_files = sorted(self.log_dir.glob("*.json"), reverse=True)
        if not log_files:
            return None
        with open(log_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        log = OperationLog(
            session_id=data["session_id"],
            start_time=data["start_time"],
            end_time=data.get("end_time", ""),
            command=data.get("command", ""),
            summary=data.get("summary", {}),
        )
        for entry_data in data.get("entries", []):
            log.entries.append(LogEntry(**entry_data))
        return log

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.log_dir.exists():
            return []
        log_files = sorted(self.log_dir.glob("*.json"), reverse=True)
        sessions = []
        for log_file in log_files[:limit]:
            with open(log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "session_id": data["session_id"],
                "command": data.get("command", ""),
                "start_time": data.get("start_time", ""),
                "summary": data.get("summary", {}),
            })
        return sessions
