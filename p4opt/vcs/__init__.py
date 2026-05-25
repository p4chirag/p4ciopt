"""VCS adapters (pluggable: git, p4)."""

from p4opt.vcs.base import VCSAdapter, Changeset
from p4opt.vcs.git_adapter import GitAdapter
from p4opt.vcs.p4_adapter import P4Adapter


def get_adapter(name: str) -> VCSAdapter:
    name = name.lower()
    if name == "git":
        return GitAdapter()
    if name == "p4":
        return P4Adapter()
    raise ValueError(f"Unknown VCS adapter: {name!r}. Expected 'git' or 'p4'.")


__all__ = ["VCSAdapter", "Changeset", "GitAdapter", "P4Adapter", "get_adapter"]
