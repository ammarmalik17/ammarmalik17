#!/usr/bin/env python3
"""Fill the self-updating sections of this profile README.

The README keeps two commented blocks that this script replaces:

    <!-- recent_projects starts -->
    ...
    <!-- recent_projects ends -->

    <!-- recent_activity starts -->
    ...
    <!-- recent_activity ends -->

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
MAX_ACTIVITY = 5
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


def describe_event(event: dict) -> str | None:
    kind = event.get("type")
    repo = (event.get("repo") or {}).get("name")
    if not kind or not repo:
        return None

    repo_url = f"https://github.com/{repo}"
    date = format_date(event.get("created_at"))
    payload = event.get("payload") or {}

    if kind == "PushEvent":
        count = payload.get("size") or 0
        if not count:
            return None
        commits = "commit" if count == 1 else "commits"
        return f"- Pushed {count} {commits} to [{repo}]({repo_url}) - {date}"

    if kind == "PullRequestEvent":
        pull = payload.get("pull_request") or {}
        if payload.get("action") != "closed" or not pull.get("merged"):
            return None
        number = payload.get("number") or pull.get("number")
        url = pull.get("html_url") or repo_url
        return f"- Merged [#{number}]({url}) in [{repo}]({repo_url}) - {date}"

    if kind == "ReleaseEvent":
        release = payload.get("release") or {}
        name = release.get("name") or release.get("tag_name")
        if not name:
            return None
        url = release.get("html_url") or repo_url
        return f"- Released [{name}]({url}) in [{repo}]({repo_url}) - {date}"

    if kind == "CreateEvent" and payload.get("ref_type") == "tag":
        tag = payload.get("ref")
        if not tag:
            return None
        url = f"{repo_url}/releases/tag/{tag}"
        return f"- Tagged [{tag}]({url}) in [{repo}]({repo_url}) - {date}"

    return None


def render_activity(events: list[dict]) -> str:
    lines = []
    seen = set()
    for event in events:
        line = describe_event(event)
        if not line:
            continue
        key = (event.get("repo", {}).get("name"), event.get("type"))
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) == MAX_ACTIVITY:
            break
    return "\n".join(lines) if lines else "- No public activity in the last 90 days."


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

    try:
        # Public events only, so private activity cannot leak into the README.
        events = api(f"/users/{USER}/events/public?per_page=30")
    except urllib.error.URLError as error:
        print(f"Skipping recent activity: {error}", file=sys.stderr)
    else:
        updated = replace_block(updated, "recent_activity", render_activity(events))

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
