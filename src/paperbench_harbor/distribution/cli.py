"""Explicit benchmark release operations, separate from automatic task creation."""

import argparse
import runpy
import sys

COMMANDS = (
    "audit-fidelity", "audit-lifesci-table-coverage", "build-lifesci-paperrecon-source",
    "build-source-archive", "consolidate-paperrecon-candidates", "create-source-tree-manifest",
    "export-trial", "materialize-onboarded-benchmark", "promote-lifesci-paperrecon-candidates",
    "promote-paperrecon-candidates", "publish-paperrecon-release", "reconstruct-upstream",
    "regress-release", "run-lifesci-paperrecon-release-candidate", "run-parity-experiment",
    "run-release-workflow", "screen-benchmark-candidate", "screen-lifesci-paperrecon-candidates",
    "verify-benchmark-candidate", "verify-paperrecon-candidates", "verify-release-provenance",
)


def main():
    parser = argparse.ArgumentParser(prog="paperbench-distribute", description=__doc__)
    parser.add_argument("operation", choices=COMMANDS)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    sys.argv = [f"paperbench-distribute {args.operation}", *args.arguments]
    runpy.run_module("paperbench_harbor.distribution." + args.operation.replace("-", "_"),
                     run_name="__main__")
