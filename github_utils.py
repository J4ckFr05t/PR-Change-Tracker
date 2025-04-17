import requests

import requests

def get_pr_data(parsed, token):
    """
    Fetch PR or compare data from GitHub depending on the parsed input.
    parsed: dict with keys:
      - type: "pr" or "compare"
      - repo: "owner/repo"
      - pr_number OR base/head depending on type
    """
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    if parsed["type"] == "pr":
        repo = parsed["repo"]
        pr_number = parsed["pr_number"]

        # Fetch PR metadata
        pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        pr_resp = requests.get(pr_url, headers=headers)
        if pr_resp.status_code != 200:
            return {"error": f"GitHub API Error: {pr_resp.status_code} - {pr_resp.text}"}
        pr_data = pr_resp.json()

        # Fetch commits
        commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
        commits_resp = requests.get(commits_url, headers=headers)
        if commits_resp.status_code != 200:
            return {"error": f"GitHub API Error: {commits_resp.status_code} - {commits_resp.text}"}
        commits_data = commits_resp.json()

    elif parsed["type"] == "compare":
        repo = parsed["repo"]
        base = parsed["base"]
        head = parsed["head"]

        compare_url = f"https://api.github.com/repos/{repo}/compare/{base}...{head}"
        compare_resp = requests.get(compare_url, headers=headers)
        if compare_resp.status_code != 200:
            return {"error": f"GitHub API Error: {compare_resp.status_code} - {compare_resp.text}"}
        compare_data = compare_resp.json()
        commits_data = compare_data.get("commits", [])
        pr_data = {
            "title": f"Comparison {base}...{head}",
            "user": {"login": None},
            "state": "compared"
        }

    else:
        return {"error": "Unsupported type in parsed data"}

    # Collect commit diffs
    commits = []
    for commit in commits_data:
        sha = commit["sha"]
        msg = commit["commit"]["message"]
        diff_url = f"https://api.github.com/repos/{repo}/commits/{sha}"
        diff_resp = requests.get(diff_url, headers={**headers, "Accept": "application/vnd.github.v3.diff"}).text

        commits.append({
            "sha": sha,
            "message": msg,
            "diff": diff_resp
        })

    return {
        "title": pr_data.get("title"),
        "author": pr_data.get("user", {}).get("login"),
        "state": pr_data.get("state"),
        "commits": commits
    }