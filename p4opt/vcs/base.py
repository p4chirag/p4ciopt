"""VCS adapter interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Changeset:
    """A logical 'set of changed files' identified by a stable id."""
    id: str
    vcs: str
    ref_from: str | None
    ref_to: str | None
    files: tuple[str, ...]


class VCSAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def get_changeset(
        self,
        ref_from: str | None = None,
        ref_to: str | None = None,
        changelist: str | None = None,
        cwd: str | None = None,
    ) -> Changeset:
        """Return a Changeset describing files modified between two refs (git)
        or in a specific changelist (p4).

        `cwd` is the working directory in which the VCS command is executed.
        Defaults to the process CWD if None.
        """
        raise NotImplementedError
