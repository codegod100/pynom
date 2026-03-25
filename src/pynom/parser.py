"""Parser for Nix build output."""

import json
import re
from datetime import datetime
from typing import Optional, Iterator
from pynom.models import (
    BuildState, Dependency, BuildStatus, ActivityType,
    BuildHistory
)


class NixParser:
    """Parse Nix build output (human-readable and JSON formats)."""
    
    # Patterns for human-readable nix-build output
    BUILDING_RE = re.compile(r"building '(/nix/store/[^']+)'")
    DERIVATION_RE = re.compile(r"building '/nix/store/([^.]+)\.drv'")
    BUILT_RE = re.compile(r"^/nix/store/([^\s]+)")
    ERROR_RE = re.compile(r"error:|builder for '(/nix/store/[^']+)' failed")
    DOWNLOAD_RE = re.compile(
        r"(downloading|fetching).*'(/nix/store/[^']+)'"
    )
    COPYING_RE = re.compile(r"copying (path|signal).*'(/nix/store/[^']+)'")
    
    def __init__(self, use_json: bool = False):
        self.use_json = use_json
        self.history = BuildHistory()
        self.state = BuildState()
        self._activity_map: dict[int, str] = {}  # activity id -> derivation name
        self._activity_type_map: dict[int, ActivityType] = {}  # activity id -> type
        self._result_data: dict[int, dict] = {}  # activity id -> result data for downloads
    
    def parse_line(self, line: str) -> Optional[str]:
        """Parse a line of nix output, return text to display."""
        line = line.rstrip('\n\r')
        
        # Store raw line for pass-through
        self.state.raw_lines.append(line)
        
        # Detect status messages from non-JSON lines (connecting, copying, etc.)
        # Skip JSON lines for status detection
        is_json = line.startswith('@nix') or line.startswith('{')
        
        if not is_json:
            # Check for builder info: building '...' on 'ssh://...'
            builder_match = re.search(r"building '.*' on '([^']+)'", line)
            if builder_match:
                builder = builder_match.group(1)
                # Extract derivation name
                drv_match = re.search(r"building '(/nix/store/[^']+)'", line)
                if drv_match:
                    drv_path = drv_match.group(1)
                    name = self._extract_name(drv_path)
                    if name in self.state.dependencies:
                        self.state.dependencies[name].builder = builder
                    self.state.status_message = f"Building {name} on {builder}"
            else:
                status_patterns = [
                    r"connecting to",
                    r"copying \d+ paths?",
                    r"copying path",
                    r"this derivation will be built",
                ]
                for pattern in status_patterns:
                    if re.search(pattern, line.lower()):
                        clean = line.strip()
                        if clean and len(clean) < 100:
                            self.state.status_message = clean
                        break
        
        if self.use_json:
            return self._parse_json_line(line)
        else:
            return self._parse_human_line(line)
    
    def _parse_human_line(self, line: str) -> Optional[str]:
        """Parse human-readable nix-build output."""
        # Check for building derivation
        match = self.BUILDING_RE.search(line) or self.DERIVATION_RE.search(line)
        if match:
            path = match.group(1)
            name = self._extract_name(path)
            
            if name not in self.state.dependencies:
                dep = Dependency(
                    name=name,
                    out_path=path,
                    status=BuildStatus.RUNNING,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
                self.state.running_builds.add(name)
            
            return f"Building {name}"
        
        # Check for downloads
        match = self.DOWNLOAD_RE.search(line)
        if match:
            verb, path = match.groups()
            name = self._extract_name(path)
            
            if name not in self.state.dependencies:
                dep = Dependency(
                    name=name,
                    out_path=path,
                    status=BuildStatus.RUNNING,
                    activity_type=ActivityType.DOWNLOAD,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
            
            return f"Downloading {name}"
        
        # Check for built outputs
        match = self.BUILT_RE.match(line)
        if match:
            path = match.group(1)
            name = self._extract_name(path)
            
            if name in self.state.dependencies:
                self.state.update_status(name, BuildStatus.DONE, datetime.now())
                # Record build time
                dep = self.state.dependencies[name]
                if dep.duration_ms:
                    self.history.record_build(name, dep.duration_ms)
            
            return line  # Pass through the output path
        
        # Check for errors
        if self.ERROR_RE.search(line):
            # Mark current builds as failed
            for name in list(self.state.running_builds):
                self.state.update_status(name, BuildStatus.FAILED)
            self.state.error = line
            return line
        
        return line  # Pass through unknown lines
    
    def _parse_json_line(self, line: str) -> Optional[str]:
        """Parse JSON internal-log format from nix 2.x."""
        # Handle @nix prefix format
        json_data = line
        if line.startswith('@nix '):
            json_data = line[5:]
        # Handle mixed JSON + text output (nix may intersperse)
        elif not line.strip().startswith('{'):
            return line  # Pass through non-JSON lines
        
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError:
            return line
        
        action = data.get("action")
        
        if action == "start":
            return self._handle_start(data)
        elif action == "stop":
            return self._handle_stop(data)
        elif action == "result":
            return self._handle_result(data)
        elif action == "msg":
            return self._handle_msg(data)
        
        return None
    
    def _handle_start(self, data: dict) -> Optional[str]:
        """Handle start JSON message."""
        activity_id = data.get("id")
        activity_type = data.get("type", 0)
        text = data.get("text", "")
        fields = data.get("fields", [])
        level = data.get("level", 4)
        
        # Track activity type for file transfers
        if activity_type >= 100:
            self._activity_type_map[activity_id] = ActivityType.DOWNLOAD
        
        # Check for derivation path in fields (build activity)
        if fields and isinstance(fields[0], str) and fields[0].endswith('.drv'):
            path = fields[0]
            name = self._extract_name(path)
            
            dep = Dependency(
                name=name,
                out_path=path,
                status=BuildStatus.RUNNING,
                activity_type=ActivityType.BUILD,
                started_at=datetime.now(),
            )
            self.state.add_dependency(dep)
            self._activity_map[activity_id] = name
            self._activity_type_map[activity_id] = ActivityType.BUILD
            return f"Building {name}"
        
        # Check text for useful activities (works for any type)
        if "building" in text.lower():
            # Extract derivation name from text
            match = re.search(r"'(/nix/store/[^']+)'", text)
            if match:
                path = match.group(1)
                name = self._extract_name(path)
                
                dep = Dependency(
                    name=name,
                    out_path=path,
                    status=BuildStatus.RUNNING,
                    activity_type=ActivityType.BUILD,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
                self._activity_map[activity_id] = name
                self._activity_type_map[activity_id] = ActivityType.BUILD
                return f"Building {name}"
        
        elif "downloading" in text.lower() or "fetching" in text.lower():
            # Try to extract path from text or fields
            path = None
            match = re.search(r"'(/nix/store/[^']+)'", text)
            if match:
                path = match.group(1)
            elif fields and isinstance(fields[0], str):
                # Fields may contain URL or store path
                path = fields[0]
            
            if path:
                name = self._extract_name(path)
                
                dep = Dependency(
                    name=name,
                    out_path=path if path.startswith('/nix/store') else None,
                    status=BuildStatus.RUNNING,
                    activity_type=ActivityType.DOWNLOAD,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
                self._activity_map[activity_id] = name
                self._activity_type_map[activity_id] = ActivityType.DOWNLOAD
                return f"Downloading {name}"
        
        elif "querying info about" in text.lower():
            # Extract store path from text or fields
            path = None
            match = re.search(r"'/nix/store/([^']+)'", text)
            if match:
                path = "/nix/store/" + match.group(1)
            elif fields and isinstance(fields[0], str) and fields[0].startswith('/nix/store'):
                path = fields[0]
            
            if path:
                name = self._extract_name(path)
                
                dep = Dependency(
                    name=name,
                    out_path=path,
                    status=BuildStatus.RUNNING,
                    activity_type=ActivityType.DOWNLOAD,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
                self._activity_map[activity_id] = name
                self._activity_type_map[activity_id] = ActivityType.DOWNLOAD
                return f"Fetching {name}"
        
        elif "copying" in text.lower():
            match = re.search(r"'(/nix/store/[^']+)'", text)
            if match:
                path = match.group(1)
                name = self._extract_name(path)
                
                # Check if upload or download
                is_upload = "to " in text.lower() or "uploading" in text.lower()
                
                dep = Dependency(
                    name=name,
                    out_path=path,
                    status=BuildStatus.RUNNING,
                    activity_type=ActivityType.UPLOAD if is_upload else ActivityType.DOWNLOAD,
                    started_at=datetime.now(),
                )
                self.state.add_dependency(dep)
                self._activity_map[activity_id] = name
                direction = "up" if is_upload else "down"
                return f"Copying {direction} {name}"
        
        # Track evaluation activities
        if "evaluating" in text.lower():
            self._activity_type_map[activity_id] = ActivityType.BUILD
            # Extract what's being evaluated for status
            if "derivation" in text.lower():
                match = re.search(r"'([^']+)'", text)
                if match:
                    deriv = match.group(1).split('/')[-1][:30]
                    self.state.status_message = f"Evaluating {deriv}..."
            return None  # Don't show evaluation, too noisy
        
        # Track querying activities
        if "querying" in text.lower():
            self.state.status_message = "Querying cache..."
            return None
        
        return None
    
    def _handle_stop(self, data: dict) -> Optional[str]:
        """Handle stop JSON message."""
        activity_id = data.get("id")
        
        if activity_id not in self._activity_map:
            return None
        
        name = self._activity_map[activity_id]
        
        if name in self.state.dependencies:
            dep = self.state.dependencies[name]
            
            # Check for errors in the activity
            has_error = False
            status = BuildStatus.FAILED if has_error else BuildStatus.DONE
            
            self.state.update_status(name, status, datetime.now())
            
            # Record build time
            if status == BuildStatus.DONE and dep.duration_ms:
                self.history.record_build(name, dep.duration_ms)
            
            del self._activity_map[activity_id]
            self._activity_type_map.pop(activity_id, None)
            
            status_str = "done" if status == BuildStatus.DONE else "FAILED"
            type_prefix = ""
            if dep.activity_type == ActivityType.DOWNLOAD:
                type_prefix = "DL "
            elif dep.activity_type == ActivityType.UPLOAD:
                type_prefix = "UP "
            
            return f"{type_prefix}{status_str} {name}"
        
        return None
    
    def _handle_result(self, data: dict) -> Optional[str]:
        """Handle result JSON message (progress updates and log lines)."""
        activity_id = data.get("id")
        result_type = data.get("type", 0)
        fields = data.get("fields", [])
        
        # Type 101 = build log lines, fields[0] is the log text
        # Type 104 = phase names (like "unpackPhase")
        if result_type in (101, 104) and fields and isinstance(fields[0], str):
            log_line = fields[0]
            if activity_id in self._activity_map:
                name = self._activity_map[activity_id]
                if name in self.state.dependencies:
                    dep = self.state.dependencies[name]
                    # Keep only last 50 log lines
                    dep.log_lines.append(log_line)
                    if len(dep.log_lines) > 50:
                        dep.log_lines = dep.log_lines[-50:]
            return None
        
        # Type 106 = file transfer progress
        # fields[0] = status (100=started, 101=progress, etc)
        # fields[1] = bytes transferred
        
        if activity_id not in self._activity_map:
            return None
        
        name = self._activity_map[activity_id]
        
        if name in self.state.dependencies:
            dep = self.state.dependencies[name]
            
            # Update download progress
            if dep.activity_type == ActivityType.DOWNLOAD and len(fields) >= 2:
                status_code = fields[0]
                bytes_transferred = fields[1] if len(fields) > 1 else 0
                
                if status_code == 101:  # Progress
                    dep.downloaded = bytes_transferred
                    # We don't know total size, so can't compute progress
                elif status_code == 100:  # Done
                    dep.downloaded = bytes_transferred
        
        return None
    
    def _handle_msg(self, data: dict) -> Optional[str]:
        """Handle msg JSON message."""
        level = data.get("level", 4)
        msg = data.get("msg", "")
        
        # Set status message for certain activities
        if msg and "evaluating" in msg.lower():
            self.state.status_message = "Evaluating..."
            return None
        
        # Level 0 = error, level 1-3 = warnings
        if level <= 0 and msg:
            self.state.error = msg
            return f"ERROR: {msg}"
        
        # Level 3 = info about paths
        if level == 3 and "will be fetched" in msg:
            # Extract path info
            match = re.search(r"(/nix/store/[^\s]+)", msg)
            if match:
                path = match.group(1)
                name = self._extract_name(path)
                return f"Fetching {name}"
        
        # Level 4 = debug, too verbose
        
        return None
    
    def _extract_name(self, path: str) -> str:
        """Extract derivation name from a store path."""
        # Handle .drv paths
        if path.endswith('.drv'):
            path = path[:-4]
        
        # Extract name from /nix/store/hash-name
        parts = path.split('/')
        if len(parts) >= 4:
            name_with_hash = parts[-1]
            # Remove hash prefix (first 32 chars are the hash)
            if len(name_with_hash) > 32 and '-' in name_with_hash:
                return name_with_hash.split('-', 1)[-1]
            return name_with_hash
        
        return path
    
    def finish(self) -> None:
        """Mark parsing as complete."""
        self.state.finished_at = datetime.now()
        
        # Mark any remaining running builds as done
        for name in list(self.state.running_builds):
            self.state.update_status(name, BuildStatus.DONE, datetime.now())


def parse_stream(stream, use_json: bool = False) -> Iterator[tuple[str, BuildState]]:
    """Parse a stream of nix output lines, yielding (display_text, state)."""
    parser = NixParser(use_json=use_json)
    
    for line in stream:
        result = parser.parse_line(line)
        # Always yield state so TUI can update, even if no display text
        yield result if result is not None else "", parser.state
    
    parser.finish()
    yield "", parser.state