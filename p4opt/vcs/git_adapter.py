"""Git VCS adapter — reads changed files via `git diff --name-only`."""
from __future__ import annotations

import subprocess

from p4opt.vcs.base import Changeset, VCSAdapter


class GitAdapter(VCSAdapter):
    name = "git"

    def get_changeset(
        self,
        ref_from: str | None = None,
        ref_to: str | None = None,
        changelist: str | None = None,
        cwd: str | None = None,
    ) -> Changeset:
        ref_from = ref_from or "HEAD~1"
        ref_to = ref_to or "HEAD"

        cmd = ["git", "diff", "--name-only", ref_from, ref_to]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "git executable not found on PATH. Install Git or use --vcs p4."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"git diff failed: {exc.stderr.strip()}"
            ) from exc

        files = tuple(
            line.strip().replace("\\", "/")
            for line in result.stdout.splitlines()
            if line.strip()
        )

        rev = subprocess.run(
            ["git", "rev-parse", ref_to],
            capture_output=True, text=True, check=False, cwd=cwd,
        )
        sha = rev.stdout.strip() or ref_to
        cs_id = f"git:{sha[:12]}"

        return Changeset(
            id=cs_id,
            vcs="git",
            ref_from=ref_from,
            ref_to=ref_to,
            files=files,
        )
