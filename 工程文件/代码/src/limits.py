"""Deployment limits shared by HTTP, tasks, persistence and algorithms."""
import json
from pathlib import Path

LIMITS = json.loads((Path(__file__).resolve().parents[1] / "config/workbench.json").read_text(encoding="utf-8"))
if any(type(value) is not int or value <= 0 for value in LIMITS.values()):
    raise ValueError("Workbench limits must be positive integers")
if LIMITS["workers"] > LIMITS["task_capacity"]:
    raise ValueError("Task capacity must be at least worker count")
