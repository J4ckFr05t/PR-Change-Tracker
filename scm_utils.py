import requests
import re
import json
from requests.auth import HTTPBasicAuth

def get_github_pr_data(parsed, token):
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
        parsed = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        pr_resp = requests.get(parsed, headers=headers)
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

def get_gitlab_pr_data(parsed, token):
    """
    Fetch MR data from GitLab based on a merge request URL.
    Returns:
        {
            title: str,
            author: str,
            state: str,
            commits: [
                { sha, message, diff }
            ]
        }
    """
    # Extract project path and MR IID
    match = re.search(r"gitlab\.com/([^/]+(?:/[^/]+)*)/-/merge_requests/(\d+)", parsed["url"])
    if not match:
        return {"error": "Invalid GitLab merge request URL"}

    project_path = match.group(1)
    mr_iid = match.group(2)

    encoded_project_path = requests.utils.quote(project_path, safe="")
    base_url = "https://gitlab.com/api/v4"
    headers = {
        "PRIVATE-TOKEN": token
    }

    # Step 1: Get project ID
    project_resp = requests.get(f"{base_url}/projects/{encoded_project_path}", headers=headers)
    if project_resp.status_code != 200:
        return {"error": f"Failed to get project: {project_resp.status_code} - {project_resp.text}"}
    project_id = project_resp.json()['id']

    # Step 2: Get MR details
    mr_resp = requests.get(f"{base_url}/projects/{project_id}/merge_requests/{mr_iid}", headers=headers)
    if mr_resp.status_code != 200:
        return {"error": f"Failed to get MR: {mr_resp.status_code} - {mr_resp.text}"}
    mr_data = mr_resp.json()

    # Step 3: Get commits
    commits_resp = requests.get(f"{base_url}/projects/{project_id}/merge_requests/{mr_iid}/commits", headers=headers)
    if commits_resp.status_code != 200:
        return {"error": f"Failed to get commits: {commits_resp.status_code} - {commits_resp.text}"}
    commits = []
    for commit in commits_resp.json():
        sha = commit["id"]
        msg = commit["message"]

        # Get raw diff for this commit (closest equivalent to GitHub diff URL)
        diff_resp = requests.get(
            f"{base_url}/projects/{project_id}/repository/commits/{sha}/diff",
            headers=headers
        )
        if diff_resp.status_code != 200:
            return {"error": f"Failed to get diff for commit {sha}"}
        
        # Merge diffs into one string (optional: you could keep per-file diffs too)
        diffs = diff_resp.json()
        combined_diff = "\n\n".join([
            f"--- {d['old_path']}\n+++ {d['new_path']}\n{d['diff']}" for d in diffs
        ])

        commits.append({
            "sha": sha,
            "message": msg,
            "diff": combined_diff
        })

    return {
        "title": mr_data.get("title"),
        "author": mr_data.get("author", {}).get("username"),
        "state": mr_data.get("state"),
        "commits": commits
    }

def get_bitbucket_pr_data(parsed, username, app_password):
    """
    Fetch pull request data from Bitbucket Cloud.
    Returns:
        {
            title: str,
            author: str,
            state: str,
            commits: [
                { sha, message, diff }
            ]
        }
    """
    # Parse URL
    match = re.search(r"bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)", parsed["url"])
    if not match:
        return {"error": "Invalid Bitbucket PR URL"}

    workspace = match.group(1)
    repo_slug = match.group(2)
    pr_id = match.group(3)

    base_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}"
    auth = HTTPBasicAuth(username, app_password)

    # Step 1: Get PR metadata
    pr_resp = requests.get(base_url, auth=auth)
    if pr_resp.status_code != 200:
        return {"error": f"Failed to fetch PR: {pr_resp.status_code} - {pr_resp.text}"}
    pr_data = pr_resp.json()

    # Step 2: Get list of commits
    commits_url = f"{base_url}/commits"
    commits_resp = requests.get(commits_url, auth=auth)
    if commits_resp.status_code != 200:
        return {"error": f"Failed to fetch commits: {commits_resp.status_code} - {commits_resp.text}"}
    commits_data = commits_resp.json()

    commits = []
    for commit in commits_data.get("values", []):
        sha = commit["hash"]
        msg = commit["message"]

        # Step 3: Get diff for each commit
        diff_url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/diff/{sha}"
        diff_resp = requests.get(diff_url, auth=auth)
        if diff_resp.status_code != 200:
            return {"error": f"Failed to fetch diff for commit {sha}: {diff_resp.status_code}"}

        commits.append({
            "sha": sha,
            "message": msg,
            "diff": diff_resp.text
        })

    return {
        "title": pr_data.get("title"),
        "author": pr_data.get("author", {}).get("nickname"),
        "state": pr_data.get("state"),
        "commits": commits
    }

def get_azure_devops_pr_data(parsed, token):
    organization = parsed["organization"]
    project = parsed["project"]
    repo_name = parsed["repo"]
    pr_id = parsed["pr_id"]

    headers = {'Content-Type': 'application/json'}
    auth = HTTPBasicAuth('', token)

    pr_url = f'https://dev.azure.com/{organization}/{project}/_apis/git/repositories/{repo_name}/pullrequests/{pr_id}?api-version=7.1-preview.1'
    pr_resp = requests.get(pr_url, auth=auth, headers=headers)

    if pr_resp.status_code != 200:
        return {"error": f"Azure DevOps API Error: {pr_resp.status_code} - {pr_resp.text}"}

    pr_data = pr_resp.json()
    pr_info = {
        "title": pr_data.get("title"),
        "author": pr_data["createdBy"]["displayName"],
        "state": pr_data["status"],
        "commits": []
    }

    commits_url = f"https://dev.azure.com/{organization}/{project}/_apis/git/repositories/{repo_name}/pullRequests/{pr_id}/commits?api-version=7.1-preview.1"
    commits_resp = requests.get(commits_url, auth=auth, headers=headers)
    if commits_resp.status_code != 200:
        return {"error": f"Azure DevOps API Error: {commits_resp.status_code} - {commits_resp.text}"}

    for commit in commits_resp.json().get("value", []):
        commit_id = commit["commitId"]
        commit_message = commit["comment"]

        # Changes (file paths and change types)
        changes_url = f"https://dev.azure.com/{organization}/{project}/_apis/git/repositories/{repo_name}/commits/{commit_id}/changes?api-version=7.1-preview.1"
        changes_resp = requests.get(changes_url, auth=auth, headers=headers)
        file_changes = []
        if changes_resp.status_code == 200:
            changes_data = changes_resp.json()
            for change in changes_data.get("changes", []):
                file_changes.append({
                    "file": change["item"]["path"],
                    "change_type": change["changeType"]
                })

        pr_info["commits"].append({
            "sha": commit_id,
            "message": commit_message,
            "files": file_changes,
            "diff": ""
        })

    return pr_info


