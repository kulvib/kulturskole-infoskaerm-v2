#!/usr/bin/env python3
"""Require a successful canonical CI push run for one exact source commit."""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--head-branch", required=True)
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    args = parser.parse_args()

    if not SHA_RE.fullmatch(args.sha):
        raise SystemExit("expected source SHA must be a full lowercase Git SHA")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    if args.repository.count("/") != 1:
        raise SystemExit("repository must be OWNER/NAME")

    workflow = quote(args.workflow, safe="")
    url = (
        f"{args.api_url.rstrip('/')}/repos/{args.repository}/actions/workflows/{workflow}/runs"
        f"?head_sha={args.sha}&status=success&per_page=100"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ClientFlow-Release-Build-CI-Gate",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API authority
        payload = json.load(response)

    runs = payload.get("workflow_runs") or []
    matches = [
        run
        for run in runs
        if run.get("head_sha") == args.sha
        and run.get("head_branch") == args.head_branch
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    if not matches:
        raise SystemExit(
            "No successful canonical CI push run found for exact source SHA "
            f"{args.sha} on {args.head_branch}"
        )
    run = sorted(matches, key=lambda item: int(item.get("run_number") or 0))[-1]
    print(f"ci_run_id={run.get('id')}")
    print(f"ci_run_number={run.get('run_number')}")
    print(f"ci_head_sha={run.get('head_sha')}")
    print("RESULT: EXACT SOURCE COMMIT HAS SUCCESSFUL CANONICAL CI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
