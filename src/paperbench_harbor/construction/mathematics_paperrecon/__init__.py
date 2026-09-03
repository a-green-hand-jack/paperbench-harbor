"""Mathematics-specific PaperRecon policy and approved-paper registry."""

from paperbench_harbor.construction.mathematics_paperrecon.plugin import MATHEMATICS_PLUGIN
from paperbench_harbor.construction.mathematics_paperrecon.screening import (
    MATHEMATICS_SCREENING_POLICY,
)

__all__ = ["MATHEMATICS_PLUGIN", "MATHEMATICS_SCREENING_POLICY"]
