import requests

def get_pr_data(repo, pr_number, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    pr_resp = requests.get(pr_url, headers=headers).json()

    commits_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/commits"
    commits_resp = requests.get(commits_url, headers=headers).json()

    commits = []
    for commit in commits_resp:
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
        "title": pr_resp["title"],
        "author": pr_resp["user"]["login"],
        "state": pr_resp["state"],
        "commits": commits
    }