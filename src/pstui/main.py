from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, Footer, Input
from textual.containers import Container
from textual import work
from textual.binding import Binding
from textual.widgets import Static
import psutil
import time
import asyncio
import os
import signal


class CustomFooter(Static):
    """Custom footer with hotkey information."""

    def __init__(self):
        super().__init__()
        self.styles.dock = "bottom"
        self.styles.background = "blue"
        self.styles.height = "1"

    def compose(self) -> ComposeResult:
        yield Static(
            "Q: Quit | F: Find | R: Refresh | K: Kill | S: Sort CPU/Mem | A: Auto-refresh | ↑/↓: Navigate"
        )


class ProcessViewer(App):
    CSS = """
    DataTable {
        height: 85%;
        border: solid green;
    }
    
    .header {
        background: $boost;
        color: $text;
        padding: 1;
        text-align: center;
    }

    Input {
        dock: top;
        margin: 1;
        border: solid $accent;
    }

    #search-box {
        height: 3;
        display: none;
    }

    #search-box.-show {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "toggle_find", "Find"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("k", "kill_process", "Kill"),
        Binding("s", "toggle_sort", "Sort CPU/Mem"),
        Binding("a", "toggle_auto_refresh", "Toggle Auto-refresh"),
    ]

    def __init__(self):
        super().__init__()
        self.search_visible = False
        self.sort_by_cpu = True
        self.selected_pid = None
        self.auto_refresh_enabled = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Search processes...", id="search-box")
        yield DataTable()
        yield CustomFooter()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "PID", "Name", "CPU %", "Memory %", "Status", "Created", "Username"
        )
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.refresh_processes()

    @work(exclusive=True)
    async def refresh_processes(self) -> None:
        while True:
            if self.auto_refresh_enabled:
                await self._refresh_table()
            await asyncio.sleep(2)

    async def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        search_text = self.query_one("#search-box").value.lower()

        # Store current selection if any
        if table.cursor_row is not None:
            try:
                self.selected_pid = int(table.get_cell_at(table.cursor_row, 0))
            except:
                self.selected_pid = None

        # Remember current cursor coordinates
        current_cursor = table.cursor_coordinate

        processes = []
        try:
            # If we have a selected PID, get its current CPU/Memory values first
            if self.selected_pid:
                selected_proc = psutil.Process(self.selected_pid)
                selected_proc.cpu_percent()  # First call to initialize CPU measurement
                await asyncio.sleep(0.1)  # Short sleep for CPU measurement

            for proc in psutil.process_iter(
                [
                    "pid",
                    "name",
                    "cpu_percent",
                    "memory_percent",
                    "status",
                    "create_time",
                    "username",
                ]
            ):
                try:
                    info = proc.info
                    if search_text and search_text not in info["name"].lower():
                        continue

                    created = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(info["create_time"])
                    )

                    processes.append(
                        {
                            "pid": info["pid"],
                            "name": info["name"],
                            "cpu": float(info["cpu_percent"]),
                            "mem": float(info.get("memory_percent", 0)),
                            "status": info["status"],
                            "created": created,
                            "username": info["username"],
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Sort processes by CPU or Memory
            sort_key = "cpu" if self.sort_by_cpu else "mem"
            processes.sort(key=lambda x: x[sort_key], reverse=True)

            # Clear and rebuild table
            table.clear()
            selected_row = None

            # Add sorted processes to table and track selected row
            for row, proc in enumerate(processes):
                table.add_row(
                    str(proc["pid"]),
                    proc["name"],
                    f"{proc['cpu']:.1f}",
                    f"{proc['mem']:.1f}",
                    proc["status"],
                    proc["created"],
                    proc["username"],
                )
                if proc["pid"] == self.selected_pid:
                    selected_row = row

            # Restore cursor position with priority to selected process
            if selected_row is not None:
                # Move to the selected process
                table.move_cursor(
                    row=selected_row,
                    column=current_cursor.column if current_cursor else 0,
                )
            elif current_cursor and current_cursor.row < len(processes):
                # Fallback: maintain current position if process not found
                table.move_cursor(row=current_cursor.row, column=current_cursor.column)

        except Exception as e:
            # If anything goes wrong, try to maintain the current position
            if current_cursor and current_cursor.row < table.row_count:
                table.move_cursor(row=current_cursor.row, column=current_cursor.column)

    def action_toggle_find(self) -> None:
        """Toggle search box visibility."""
        search_box = self.query_one("#search-box")
        self.search_visible = not self.search_visible
        search_box.toggle_class("-show")
        if self.search_visible:
            search_box.focus()

    def action_refresh_now(self) -> None:
        """Manually trigger a refresh."""
        asyncio.create_task(self._refresh_table())

    def action_kill_process(self) -> None:
        """Kill the selected process."""
        table = self.query_one(DataTable)
        if table.cursor_row is None:
            self.notify("No process selected")
            return

        try:
            pid = int(table.get_cell_at(table.cursor_row, 0))
            proc = psutil.Process(pid)
            proc.terminate()  # Try SIGTERM first
            self.notify(f"Process {pid} ({proc.name()}) terminated")
            asyncio.create_task(self._refresh_table())
        except psutil.NoSuchProcess:
            self.notify(f"Process {pid} not found")
        except psutil.AccessDenied:
            try:
                # Try with sudo if available
                os.system(f"sudo kill {pid}")
                self.notify(f"Attempted to kill process {pid} with sudo")
            except:
                self.notify(f"Permission denied to kill process {pid}")
        except Exception as e:
            self.notify(f"Error: {str(e)}")

    def action_toggle_sort(self) -> None:
        """Toggle between CPU and Memory sorting."""
        self.sort_by_cpu = not self.sort_by_cpu
        self.notify(f"Sorting by {'CPU' if self.sort_by_cpu else 'Memory'} usage")
        asyncio.create_task(self._refresh_table())

    def action_toggle_auto_refresh(self) -> None:
        """Toggle auto-refresh on/off."""
        self.auto_refresh_enabled = not self.auto_refresh_enabled
        self.notify(
            f"Auto-refresh {'enabled' if self.auto_refresh_enabled else 'disabled'}"
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        asyncio.create_task(self._refresh_table())


def main():
    app = ProcessViewer()
    app.run()


if __name__ == "__main__":
    main()
