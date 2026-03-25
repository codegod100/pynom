"""Data models for build tracking."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
from pathlib import Path
import json
import csv


class BuildStatus(Enum):
    """Status of a build or download."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    WAITING = "waiting"


class ActivityType(Enum):
    """Type of activity being tracked."""
    BUILD = "build"
    DOWNLOAD = "download"
    UPLOAD = "upload"


@dataclass
class Dependency:
    """A single dependency being built/downloaded."""
    name: str
    out_path: Optional[str] = None
    status: BuildStatus = BuildStatus.PENDING
    activity_type: ActivityType = ActivityType.BUILD
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    parent: Optional[str] = None
    children: list[str] = field(default_factory=list)
    progress: float = 0.0  # 0.0 to 1.0 for downloads
    size: Optional[int] = None  # Size in bytes (for downloads)
    downloaded: int = 0  # Bytes downloaded so far
    log_lines: list[str] = field(default_factory=list)  # Build output lines
    
    @property
    def status_text(self) -> str:
        """Get status as simple text."""
        return {
            BuildStatus.RUNNING: "running",
            BuildStatus.DONE: "done",
            BuildStatus.FAILED: "FAILED",
            BuildStatus.PENDING: "pending",
            BuildStatus.WAITING: "waiting",
        }[self.status]
    
    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Get elapsed time in seconds if running."""
        if self.started_at and self.status == BuildStatus.RUNNING:
            return (datetime.now() - self.started_at).total_seconds()
        return None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get duration in seconds if completed."""
        if self.duration_ms:
            return self.duration_ms / 1000
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


@dataclass
class BuildState:
    """Overall state of a Nix build."""
    dependencies: dict[str, Dependency] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    status_message: Optional[str] = None  # Current status like "connecting to..."
    
    # Track builds in progress
    running_builds: set[str] = field(default_factory=set)
    running_downloads: set[str] = field(default_factory=set)
    running_uploads: set[str] = field(default_factory=set)
    
    # Completed counts
    completed_builds: int = 0
    completed_downloads: int = 0
    failed_builds: int = 0
    
    @property
    def total_time_seconds(self) -> float:
        """Get total elapsed time."""
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds()
    
    @property
    def total_builds(self) -> int:
        """Total number of builds."""
        return len([d for d in self.dependencies.values() 
                   if d.activity_type == ActivityType.BUILD])
    
    @property
    def total_downloads(self) -> int:
        """Total number of downloads."""
        return len([d for d in self.dependencies.values() 
                   if d.activity_type == ActivityType.DOWNLOAD])
    
    def add_dependency(self, dep: Dependency) -> None:
        """Add a dependency to tracking."""
        self.dependencies[dep.name] = dep
        
        if dep.status == BuildStatus.RUNNING:
            if dep.activity_type == ActivityType.BUILD:
                self.running_builds.add(dep.name)
            elif dep.activity_type == ActivityType.DOWNLOAD:
                self.running_downloads.add(dep.name)
            elif dep.activity_type == ActivityType.UPLOAD:
                self.running_uploads.add(dep.name)
    
    def update_status(self, name: str, status: BuildStatus, 
                      finished_at: Optional[datetime] = None) -> None:
        """Update the status of a dependency."""
        if name not in self.dependencies:
            return
        
        dep = self.dependencies[name]
        old_status = dep.status
        dep.status = status
        
        if finished_at:
            dep.finished_at = finished_at
            if dep.started_at:
                dep.duration_ms = int((finished_at - dep.started_at).total_seconds() * 1000)
        
        if old_status == BuildStatus.RUNNING:
            if dep.activity_type == ActivityType.BUILD:
                self.running_builds.discard(name)
            elif dep.activity_type == ActivityType.DOWNLOAD:
                self.running_downloads.discard(name)
            elif dep.activity_type == ActivityType.UPLOAD:
                self.running_uploads.discard(name)
        
        if status == BuildStatus.DONE:
            if dep.activity_type == ActivityType.BUILD:
                self.completed_builds += 1
            elif dep.activity_type == ActivityType.DOWNLOAD:
                self.completed_downloads += 1
        elif status == BuildStatus.FAILED:
            self.failed_builds += 1
    
    def get_tree(self) -> list[tuple[Dependency, int]]:
        """Get dependencies as a tree with indentation levels."""
        result: list[tuple[Dependency, int]] = []
        visited: set[str] = set()
        
        def visit(name: str, depth: int) -> None:
            if name in visited or name not in self.dependencies:
                return
            visited.add(name)
            dep = self.dependencies[name]
            result.append((dep, depth))
            for child in dep.children:
                visit(child, depth + 1)
        
        roots = [d for d in self.dependencies.values() if d.parent is None]
        for root in sorted(roots, key=lambda d: d.name):
            visit(root.name, 0)
        
        return result


@dataclass
class BuildReport:
    """A saved build report for history tracking."""
    name: str
    duration_ms: int
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BuildReport":
        return cls(
            name=data["name"],
            duration_ms=data["duration_ms"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class BuildHistory:
    """Stores and retrieves build time history."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            import os
            cache_dir = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")) / "pynom"
        self.cache_dir = Path(cache_dir).expanduser()
        self.history_file = self.cache_dir / "build-reports.csv"
        self._reports: dict[str, list[BuildReport]] = {}
        self._loaded = False
    
    def _ensure_loaded(self) -> None:
        """Load history from disk if not already loaded."""
        if self._loaded:
            return
        self._loaded = True
        
        if not self.history_file.exists():
            return
        
        try:
            with open(self.history_file, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    report = BuildReport(
                        name=row["name"],
                        duration_ms=int(row["duration_ms"]),
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                    )
                    if report.name not in self._reports:
                        self._reports[report.name] = []
                    self._reports[report.name].append(report)
        except Exception:
            pass
    
    def get_average_time(self, name: str) -> Optional[float]:
        """Get average build time in seconds for a derivation."""
        self._ensure_loaded()
        
        if name not in self._reports or not self._reports[name]:
            return None
        
        reports = self._reports[name]
        recent = reports[-5:]
        total_ms = sum(r.duration_ms for r in recent)
        return total_ms / len(recent) / 1000
    
    def record_build(self, name: str, duration_ms: int) -> None:
        """Record a build time for future predictions."""
        self._ensure_loaded()
        
        report = BuildReport(name=name, duration_ms=duration_ms)
        
        if name not in self._reports:
            self._reports[name] = []
        self._reports[name].append(report)
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.history_file, "a", newline="") as f:
            writer = csv.writer(f)
            if not self.history_file.exists() or self.history_file.stat().st_size == 0:
                writer.writerow(["name", "duration_ms", "timestamp"])
            writer.writerow([name, duration_ms, report.timestamp.isoformat()])
    
    def predict_remaining(self, state: BuildState) -> Optional[float]:
        """Predict remaining build time based on history."""
        self._ensure_loaded()
        
        pending = [d for d in state.dependencies.values() 
                   if d.status in (BuildStatus.PENDING, BuildStatus.WAITING)]
        
        if not pending:
            return None
        
        total_predicted = 0.0
        unknown = 0
        
        for dep in pending:
            avg = self.get_average_time(dep.name)
            if avg is not None:
                total_predicted += avg
            else:
                unknown += 1
        
        if unknown > 0 and total_predicted > 0:
            known_avg = total_predicted / max(1, len(pending) - unknown)
            total_predicted += unknown * known_avg
        
        return total_predicted if total_predicted > 0 else None