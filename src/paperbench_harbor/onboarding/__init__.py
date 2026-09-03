"""Contracts shared by the human-gated benchmark onboarding workflow."""

from paperbench_harbor.onboarding.candidate import (
    BenchmarkCandidate,
    LayoutApproval,
    OnboardingError,
    parse_candidate,
    read_layout_approval,
)

__all__ = [
    "BenchmarkCandidate",
    "LayoutApproval",
    "OnboardingError",
    "parse_candidate",
    "read_layout_approval",
]
