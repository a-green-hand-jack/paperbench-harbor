# Copyright 2026 Google LLC (upstream logic); shim adapted by paperbench-harbor.
# Licensed under the Apache License, Version 2.0 (the "License").

"""Minimal common utils for the vendored PaperOrchestra autoraters."""

import os


def create_log_folder(folder_name):
    os.makedirs(folder_name, exist_ok=True)
    log_path = os.path.join(folder_name, "log.txt")
    return log_path
