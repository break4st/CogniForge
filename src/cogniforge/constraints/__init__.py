"""Constraint system — load per-role behavioral constraints from .md files.

Constraints are loaded from .cogniforge/constraints/{role}.md. When the file doesn't
exist, a built-in default is used, ensuring the system works in any project.
"""

from cogniforge.constraints.constraint_loader import ConstraintLoader

__all__ = ["ConstraintLoader"]
