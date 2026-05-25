"""Perforce (P4) VCS adapter.

Reads files affected by a changelist via `p4 describe -s <CL>`.
Falls back to `p4 opened` for pending work (when no changelist provided).
"""
from __future__ import annotations

import re
import subprocess

from p4opt.vcs.base import Changeset, VCSAdapter


# Lines in `p4 describe -s` output look like:
#   //depot/path/to/file.py#3 edit
_AFFECTED_LINE = re.compile(r"^(//[^#\s]+)#\d+\s+\w+\s*$")


class P4Adapter(VCSAdapter):
    name = "p4"

    def get_changeset(
        self,
        ref_from: str | None = None,
        ref_to: str | None = None,
        changelist: str | None = None,
        cwd: str | None = None,
    ) -> Changeset:
        if changelist:
            files = self._files_in_changelist(changelist, cwd=cwd)
            cs_id = f"p4:cl{changelist}"
        else:
            files = self._files_opened(cwd=cwd)
            cs_id = "p4:opened"

        return Changeset(
            id=cs_id,
            vcs="p4",
            ref_from=None,
            ref_to=changelist,
            files=files,
        )

    @staticmethod
    def _run(cmd: list[str], cwd: str | None = None) -> str:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "p4 executable not found on PATH. Install Helix Core CLI or use --vcs git."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"{' '.join(cmd)} failed: {exc.stderr.strip()}"
            ) from exc
        return result.stdout

    def _files_in_changelist(self, cl: str, cwd: str | None = None) -> tuple[str, ...]:
        out = self._run(["p4", "describe", "-s", cl], cwd=cwd)
        files: list[str] = []
        in_affected = False
        for line in out.splitlines():
            if line.startswith("Affected files"):
                in_affected = True
                continue
            if not in_affected:
                continue
            m = _AFFECTED_LINE.match(line.strip())
            if m:
                files.append(m.group(1))
        return tuple(files)

    def _files_opened(self, cwd: str | None = None) -> tuple[str, ...]:
        out = self._run(["p4", "opened"], cwd=cwd)
        files: list[str] = []
        for line in out.splitlines():
            # "//depot/path#rev - edit default change (text)"
            depot = line.split("#", 1)[0].strip()
            if depot.startswith("//"):
                files.append(depot)
        return tuple(files)
