"""Small, first-class tasks used to exercise the Harbor integration."""

from paperbench_harbor.smoke.hello_world import (
    HELLO_WORLD_TASK_ID,
    build_hello_world_task,
)

__all__ = ["HELLO_WORLD_TASK_ID", "build_hello_world_task"]
