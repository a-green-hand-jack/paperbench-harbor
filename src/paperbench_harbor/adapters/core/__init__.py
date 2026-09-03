"""Shared, spec-driven mechanics for benchmark adapters."""

from paperbench_harbor.adapters.core.convert import (
    TaskDirectories,
    create_template_environment,
    load_dataset_manifest,
    prepare_task_directories,
    prepare_task_output,
    render_templates,
    task_id_for,
    write_dataset_manifest,
)

__all__ = [
    "TaskDirectories",
    "create_template_environment",
    "load_dataset_manifest",
    "prepare_task_directories",
    "prepare_task_output",
    "render_templates",
    "task_id_for",
    "write_dataset_manifest",
]
