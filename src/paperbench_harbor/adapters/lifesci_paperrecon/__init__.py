"""LifeSci-PaperRecon Harbor adapter.

LifeSci-PaperRecon is this project's own biology / life-sciences paper-writing
benchmark. It has no upstream implementation to mirror, so there is no parallel
Harbor converter here: the corpus is built into the same generic layout
PaperWrite-Bench uses, and `adapters.paperwrite_bench.converter` wraps it with
the identity metadata declared in :mod:`.harbor`.
"""

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
    BENCHMARK,
    TASK_ID_PREFIX,
    lifesci_paperrecon_conversion_config,
)

__all__ = ["BENCHMARK", "TASK_ID_PREFIX", "lifesci_paperrecon_conversion_config"]
