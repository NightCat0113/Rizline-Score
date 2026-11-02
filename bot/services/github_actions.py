"""Trigger GitHub Actions workflows from the bot (used on slim hosts like Altare)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class GitHubActionsError(Exception):
    pass


def dispatch_workflow(
    *,
    token: str,
    repository: str,
    workflow: str,
    ref: str = "main",
) -> None:
    """Start a workflow_dispatch run. Raises GitHubActionsError on failure."""
    repo = repository.strip().strip("/")
    if "/" not in repo or repo.count("/") != 1:
        raise GitHubActionsError("GITHUB_REPOSITORY must look like owner/name")
    name = workflow.strip() or "refresh-game-data.yml"
    if not name.endswith(".yml") and not name.endswith(".yaml"):
        name = f"{name}.yml"
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{name}/dispatches"
    body = json.dumps({"ref": ref.strip() or "main"}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "rizline-lookup-bot",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            # 204 No Content is success for workflow_dispatch.
            if response.status not in (204, 200):
                raise GitHubActionsError(f"GitHub returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise GitHubActionsError(f"GitHub HTTP {exc.code}: {detail or exc.reason}") from None
    except urllib.error.URLError as exc:
        raise GitHubActionsError(f"Could not reach GitHub: {exc.reason}") from None
