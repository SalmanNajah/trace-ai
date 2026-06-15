from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def parse_github_url(github_url: str) -> tuple[str, str]:
    match = re.search(r"github\.com/([^/]+)/([^/.]+)", github_url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {github_url}")
    return match.group(1), match.group(2)


class GitHubRepoManager:
    def __init__(self, data_root: Path) -> None:
        self.clone_root = data_root / "repos"

    def clone_or_pull(self, github_url: str, branch: str = "main") -> Path:
        owner, repo = parse_github_url(github_url)
        local_path = self.clone_root / owner / repo
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if local_path.exists():
            try:
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=local_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "pull"],
                    cwd=local_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError:
                shutil.rmtree(local_path)
                self._clone(github_url, branch, local_path)
        else:
            self._clone(github_url, branch, local_path)

        return local_path

    def _clone(self, github_url: str, branch: str, local_path: Path) -> None:
        try:
            subprocess.run(
                ["git", "clone", "--branch", branch, github_url, str(local_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Git clone failed: {exc.stderr}") from exc

    def get_latest_commit_sha(self, local_path: Path) -> str:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=local_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return res.stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to get latest commit SHA: {exc.stderr}") from exc

    def get_commit_diff(self, local_path: Path, old_sha: str, new_sha: str) -> list[str]:
        try:
            res = subprocess.run(
                ["git", "diff", "--name-only", old_sha, new_sha],
                cwd=local_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to get git diff: {exc.stderr}") from exc
