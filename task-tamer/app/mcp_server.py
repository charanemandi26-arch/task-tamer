import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TaskTamer")

# Simple JSON data file in the app directory
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_tamer_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tasks": [], "events": []}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving data: {e}")

@mcp.tool()
def get_tasks() -> str:
    """Get the list of all current tasks and their priority."""
    data = load_data()
    return json.dumps(data["tasks"], indent=2)

@mcp.tool()
def add_task(title: str, priority: str = "medium", due_date: str = None) -> str:
    """Add a new task with a specific priority and optional due date.
    
    Args:
        title: The title/description of the task.
        priority: The priority of the task (low, medium, high).
        due_date: Optional due date/time.
    """
    data = load_data()
    task = {
        "id": len(data["tasks"]) + 1,
        "title": title,
        "priority": priority,
        "due_date": due_date,
        "status": "pending"
    }
    data["tasks"].append(task)
    save_data(data)
    return f"Successfully added task: '{title}' (ID: {task['id']}, Priority: {priority})"

@mcp.tool()
def schedule_focus_block(title: str, start_time: str, duration_minutes: int) -> str:
    """Schedule a focus block in the calendar.
    
    Args:
        title: The name of the focus block (e.g. 'Code Review').
        start_time: Start date and time (e.g. '2026-07-01 10:00').
        duration_minutes: The duration of the focus block in minutes.
    """
    data = load_data()
    event = {
        "id": len(data["events"]) + 1,
        "title": title,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "type": "focus_block"
    }
    data["events"].append(event)
    save_data(data)
    return f"Successfully scheduled focus block: '{title}' at {start_time} for {duration_minutes} mins."

@mcp.tool()
def get_calendar_events() -> str:
    """Get all scheduled calendar events and focus blocks."""
    data = load_data()
    return json.dumps(data["events"], indent=2)

if __name__ == "__main__":
    mcp.run()
