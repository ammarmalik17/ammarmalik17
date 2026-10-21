#!/usr/bin/env python3
"""Fill the self-updating section of this profile README.

The README keeps one commented block that this script replaces:

    <!-- recent_projects starts -->
    ...
    <!-- recent_projects ends -->

It runs from GitHub Actions on a schedule and on every push.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

USER = "ammarmalik17"
README = "README.md"
API = "https://api.github.com"
EXCLUDED_REPOS = {"ammarmalik17", "portfolio"}
MAX_PROJECTS = 5
DESCRIPTION_LIMIT = 120


def api(path: str) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ammarmalik17-profile-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def format_date(value: str | None) -> str:
    if not value:
        return "unknown date"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%b %d, %Y")


def clean_text(value: str) -> str:
    """Collapse whitespace and keep the README free of em dashes."""
    text = " ".join(value.split())
    return text.replace("\u2014", " - ").replace("\u2013", "-")


def fetch_repos() -> list[dict]:
    repos: list[dict] = []
    page = 1
    while page <= 10:
        batch = api(f"/users/{USER}/repos?per_page=100&sort=pushed&page={page}")
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def select_repos(repos: list[dict]) -> list[dict]:
    """Keep public, original projects, newest first.

    /users/{user}/repos already returns public repositories only. The explicit
    private check is a second line of defense so private work can never leak
    into the README if that endpoint changes.
    """
    selected = [
        repo
        for repo in repos
        if not repo.get("fork")
        and not repo.get("private")
        and repo["name"] not in EXCLUDED_REPOS
    ]
    selected.sort(key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    return selected


def render_projects(repos: list[dict]) -> str:
    lines = []
    for repo in repos[:MAX_PROJECTS]:
        description = clean_text(repo.get("description") or "")
        if len(description) > DESCRIPTION_LIMIT:
            description = description[: DESCRIPTION_LIMIT - 3].rstrip(" ,.;") + "..."

        meta = []
        if repo.get("language"):
            meta.append(repo["language"])
        if repo.get("stargazers_count"):
            meta.append(f"{repo['stargazers_count']} stars")
        meta.append(f"updated {format_date(repo.get('pushed_at'))}")

        line = f"- [{repo['name']}]({repo['html_url']})"
        if description:
            line += f" - {description}"
        line += f" ({', '.join(meta)})"
        lines.append(line)

    return "\n".join(lines) if lines else "- No public repositories found."


def replace_block(text: str, name: str, content: str) -> str:
    pattern = re.compile(
        rf"(<!-- {re.escape(name)} starts -->\n).*?(\n<!-- {re.escape(name)} ends -->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(f"README is missing the {name} block")
    return pattern.sub(lambda match: match.group(1) + content + match.group(2), text, count=1)


def main() -> int:
    with open(README, encoding="utf-8") as handle:
        original = handle.read()

    repos = select_repos(fetch_repos())

    updated = replace_block(original, "recent_projects", render_projects(repos))

    if updated == original:
        print("README is already up to date")
        return 0

    with open(README, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    print("README updated")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as error:
        print(f"GitHub API error {error.code}: {error.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as error:
        print(f"Network error: {error.reason}", file=sys.stderr)
        sys.exit(1)
