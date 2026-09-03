"""Physics-specific PaperRecon policy and approved-paper registry."""

from paperbench_harbor.construction.physics_paperrecon.plugin import PHYSICS_PLUGIN
from paperbench_harbor.construction.physics_paperrecon.screening import PHYSICS_SCREENING_POLICY

__all__ = ["PHYSICS_PLUGIN", "PHYSICS_SCREENING_POLICY"]
