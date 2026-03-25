"""Terminal display for build progress."""

import sys
import time
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TaskID
from rich.table import Table
from rich.text import Text

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
        """Render the build state as a rich panel with progress bars."""
        # Create progress bars
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            expand=False,
        )
        
        # Overall build progress
        total_tasks = state.total_builds + state.total_downloads
        done_tasks = state.completed_builds + state.completed_downloads
        running_tasks = len(state.running_builds) + len(state.running_downloads)
        
        if total_tasks > 0:
            overall_task = progress.add_task(
                f"[cyan]Overall[/]",
                total=total_tasks,
                completed=done_tasks,
            )
        
        # Running builds
        for name in sorted(state.running_builds):
            dep = state.dependencies.get(name)
            if dep:
                elapsed = dep.elapsed_seconds or 0
                predicted = self.history.get_average_time(name)
                
                if predicted and predicted > 0:
                    pct = min(elapsed / predicted, 0.99)  # Cap at 99% while running
                    progress.add_task(
                        f"  [yellow]{name[:30]}[/]",
                        total=100,
                        completed=int(pct * 100),
                    )
                else:
                    # No prediction, show indeterminate
                    progress.add_task(
                        f"  [yellow]{name[:30]}[/]",
                        total=None,
                    )
        
        # Running downloads
        for name in sorted(state.running_downloads):
            dep = state.dependencies.get(name)
            if dep:
                if dep.size and dep.size > 0:
                    progress.add_task(
                        f"  [blue]DL {name[:25]}[/]",
                        total=dep.size,
                        completed=dep.downloaded,
                    )
                else:
                    progress.add_task(
                        f"  [blue]DL {name[:25]}[/]",
                        total=None,
                    )
        
        # Build progress bar table
        lines: list[str] = []
        
        # Header with counts
        if total_tasks > 0:
            status_parts = []
            if state.failed_builds > 0:
                status_parts.append(f"[red]{state.failed_builds} failed[/]")
            if running_tasks > 0:
                status_parts.append(f"[yellow]{running_tasks} running[/]")
            if done_tasks > 0:
                status_parts.append(f"[green]{done_tasks} done[/]")
            
            lines.append(" ".join(status_parts))
            lines.append("")
        
        # Recent log lines from running builds
        log_lines_shown = 0
        max_log_lines = 15
        for name in sorted(state.running_builds):
            dep = state.dependencies.get(name)
            if dep and dep.log_lines:
                # Show last few log lines
                recent_logs = dep.log_lines[-8:]
                for log in recent_logs:
                    if log_lines_shown >= max_log_lines:
                        break
                    # Truncate long lines
                    display_log = log[:70] if len(log) > 70 else log
                    lines.append(f"  [dim]{display_log}[/]")
                    log_lines_shown += 1
        
        if log_lines_shown > 0:
            lines.append("")
        
        # Recent completions (last 5)
        completed = [
            (dep, depth) for dep, depth in state.get_tree()
            if dep.status == BuildStatus.DONE
        ][-5:]
        
        if completed:
            lines.append("[dim]Completed:[/]")
            for dep, depth in completed:
                duration = f" {self.format_time(dep.duration_seconds)}" if dep.duration_seconds else ""
                lines.append(f"  [dim]{dep.name}{duration}[/]")
        
        # Error display
        if state.error:
            lines.append("")
            lines.append(f"[red bold]Error:[/] {state.error}")
        
        # Combine into panel
        if state.finished_at and total_tasks == 0:
            # Build finished but no tracked items (cached or fast)
            content = "[dim]Build completed (cached or no builds tracked)[/]"
        elif total_tasks == 0 and not state.error:
            # Show status message or waiting
            if state.status_message:
                content = f"[dim]{state.status_message}[/]"
            else:
                content = "[dim]Waiting for build output...[/]"
        else:
            # Build content with progress bar
            from rich.layout import Layout
            from rich.text import Text
            
            content_table = Table.grid(padding=0)
            content_table.add_column()
            
            # Add progress renderable
            if total_tasks > 0 or running_tasks > 0:
                content_table.add_row(progress)
                content_table.add_row("")
            elif state.status_message:
                # Show status when no builds running yet
                content_table.add_row(Text.from_markup(f"[dim]{state.status_message}[/]"))
                content_table.add_row("")
            
            # Add text lines
            for line in lines:
                content_table.add_row(Text.from_markup(line))
            
            content = content_table
        
        # Summary title
        elapsed = self.format_time(state.total_time_seconds)
        title = f" {elapsed} "
        
        if state.failed_builds > 0:
            title = f"[red] FAIL [/]{title}"
        elif state.finished_at:
            title = f"[green] DONE [/]{title}"
        
        return Panel(
            content,
            title=title,
            title_align="left",
            border_style="blue" if not state.error else "red",
            padding=(0, 1),
        )
    
    @contextmanager  
    def live_display(self):
        """Context manager for live updating display."""
        live = Live(
            console=self.console,
            refresh_per_second=20,
            transient=False,
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
        
        for output_text, current_state in parse_stream(stream, use_json=self.use_json):
            state = current_state
            
            if self.show_pass_through and output_text:
                self.console.print(output_text)
        
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