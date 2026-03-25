"""Terminal display for build progress."""

import sys
import time
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.style import Style

from pynom.models import BuildState, BuildStatus, ActivityType, BuildHistory


class BuildDisplay:
    """Rich-based terminal display for build progress."""
    
    def __init__(self, show_pass_through: bool = True, use_json: bool = False):
        self.console = Console(stderr=False, force_terminal=True)
        self.show_pass_through = show_pass_through
        self.use_json = use_json
        self.history = BuildHistory()
        self._last_render_time: float = 0
        self._render_interval: float = 0.05  # 20 FPS max
    
    def format_time(self, seconds: float) -> str:
        """Format seconds into human readable time."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m{secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h{mins}m"
    
    def format_size(self, bytes_val: int) -> str:
        """Format bytes into human readable size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f}TB"
    
    def render_state(self, state: BuildState) -> Panel:
        """Render the build state as a rich panel."""
        # Create main content
        lines: list[str] = []
        
        # Running builds section
        if state.running_builds:
            lines.append("[bold cyan]Building:[/]")
            for name in sorted(state.running_builds):
                dep = state.dependencies.get(name)
                if dep:
                    elapsed = dep.elapsed_seconds
                    elapsed_str = self.format_time(elapsed) if elapsed else ""
                    predicted = self.history.get_average_time(name)
                    
                    time_info = ""
                    if elapsed_str:
                        time_info = f" [dim]⏱︎{elapsed_str}[/]"
                        if predicted and elapsed:
                            remaining = predicted - elapsed
                            if remaining > 0:
                                time_info += f" [dim]~{self.format_time(remaining)}[/]"
                    
                    lines.append(f"  ⏵ {name}{time_info}")
            lines.append("")
        
        # Running downloads section  
        if state.running_downloads:
            lines.append("[bold yellow]Downloading:[/]")
            for name in sorted(state.running_downloads):
                dep = state.dependencies.get(name)
                if dep:
                    size_info = ""
                    if dep.size:
                        size_info = f" ({self.format_size(dep.size)})"
                    progress_str = ""
                    if dep.progress > 0:
                        pct = dep.progress * 100
                        progress_str = f" [{pct:.0f}%]"
                    lines.append(f"  ↓⏵ {name}{size_info}{progress_str}")
            lines.append("")
        
        # Build tree (recent completions and waiting)
        tree = state.get_tree()
        if tree:
            visible_deps = [t for t in tree 
                          if t[0].status in (BuildStatus.DONE, BuildStatus.FAILED, BuildStatus.WAITING)]
            if visible_deps:
                lines.append("[bold]Dependencies:[/]")
                for dep, depth in visible_deps[-20:]:  # Show last 20
                    indent = "  " * depth
                    color = {
                        BuildStatus.DONE: "green",
                        BuildStatus.FAILED: "red",
                        BuildStatus.WAITING: "dim",
                        BuildStatus.PENDING: "dim",
                        BuildStatus.RUNNING: "cyan",
                    }[dep.status]
                    
                    duration_str = ""
                    if dep.duration_seconds:
                        duration_str = f" [dim]⏱︎{self.format_time(dep.duration_seconds)}[/]"
                    
                    lines.append(f"  {indent}[{color}]{dep.icon}[/{color}] {dep.name}{duration_str}")
        
        # Summary bar
        summary_parts = []
        
        # Total time
        total_time = self.format_time(state.total_time_seconds)
        summary_parts.append(f"[bold]∑ {total_time}[/]")
        
        # Build counts
        if state.total_builds > 0:
            done = state.completed_builds
            total = state.total_builds
            running = len(state.running_builds)
            failed = state.failed_builds
            
            if failed > 0:
                summary_parts.append(f"[red]⚠ {failed} failed[/]")
            
            if running > 0:
                summary_parts.append(f"[cyan]⏵ {running} building[/]")
            
            summary_parts.append(f"[green]✔ {done}/{total}[/]")
        
        # Download counts
        if state.completed_downloads > 0:
            summary_parts.append(f"[yellow]↓✔ {state.completed_downloads}[/]")
        
        # Prediction
        predicted = self.history.predict_remaining(state)
        if predicted and predicted > 1:
            summary_parts.append(f"[dim]~{self.format_time(predicted)} left[/]")
        
        # Error display
        if state.error:
            lines.append("")
            lines.append(f"[bold red]Error:[/] {state.error}")
        
        # Combine
        content = "\n".join(lines) if lines else "[dim]Waiting for build output...[/]"
        summary = " │ ".join(summary_parts) if summary_parts else ""
        
        # Create panel
        return Panel(
            content,
            title=summary or "pynom",
            title_align="left",
            border_style="blue",
            padding=(0, 1),
        )
    
    def render_output(self, text: str, state: BuildState) -> Panel:
        """Render pass-through output with status panel."""
        content = self.render_state(state)
        return content
    
    @contextmanager  
    def live_display(self):
        """Context manager for live updating display."""
        live = Live(
            console=self.console,
            refresh_per_second=20,
            transient=False,  # Keep output after done
        )
        live.start()
        try:
            yield live
        finally:
            live.stop()
    
    def update(self, live: Live, state: BuildState) -> None:
        """Update the live display with current state."""
        now = time.time()
        if now - self._last_render_time < self._render_interval:
            return
        self._last_render_time = now
        
        panel = self.render_state(state)
        live.update(panel)
    
    def print_final(self, state: BuildState) -> None:
        """Print the final summary."""
        self.console.print()
        self.console.print(self.render_state(state))
        
        if state.error:
            self.console.print(f"\n[bold red]Build failed![/]")
        elif state.finished_at:
            self.console.print(f"\n[bold green]Build completed in {self.format_time(state.total_time_seconds)}[/]")


class StreamDisplay:
    """Display that shows both pass-through output and status panel."""
    
    def __init__(self, show_pass_through: bool = True, use_json: bool = False):
        self.show_pass_through = show_pass_through
        self.use_json = use_json
        self.display = BuildDisplay(show_pass_through=show_pass_through, use_json=use_json)
        self.console = Console(stderr=False)
    
    def run(self, stream, status_lines: int = 10) -> BuildState:
        """Run the display over a stream, returns final state."""
        from pynom.parser import parse_stream
        
        state = None
        
        # In pass-through mode, we print the output and periodically
        # print a status line
        for output_text, current_state in parse_stream(stream, use_json=self.use_json):
            state = current_state
            
            # Print pass-through output
            if self.show_pass_through and output_text:
                self.console.print(output_text)
            
            # Periodically show status (every N lines or seconds)
            # For now, just track state
        
        # Print final summary
        if state:
            self.display.print_final(state)
        
        return state or BuildState()
    
    def run_with_tui(self, stream) -> BuildState:
        """Run with a live TUI overlay (hides pass-through)."""
        from pynom.parser import parse_stream
        
        state = BuildState()
        
        with self.display.live_display() as live:
            for output_text, current_state in parse_stream(stream, use_json=self.use_json):
                state = current_state
                self.display.update(live, state)
        
        self.display.print_final(state)
        return state