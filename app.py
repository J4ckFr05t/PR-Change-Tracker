from flask import Flask, render_template, request
from github_utils import get_pr_data
from diff_parser import parse_diff_by_commit
from save_to_json import save_summary_to_json
from dotenv import load_dotenv
import os

app = Flask(__name__)

load_dotenv()
github_token = os.getenv("GITHUB_API_KEY")


@app.route("/", methods=["GET", "POST"])
def index():
    summary = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        try:
            if action == "analyze":
                pr_url = request.form.get("pr_url")
                repo, pr_number = parse_pr_url(pr_url)

                pr_data = get_pr_data(repo, pr_number, github_token)
                commit_data = parse_diff_by_commit(pr_data["commits"])

                summary = {
                    "metadata": {
                        "title": pr_data["title"],
                        "author": pr_data["author"],
                        "state": pr_data["state"],
                        "url": pr_url
                    },
                    "commits": commit_data
                }

            elif action == "save":
                pr_url = request.form.get("pr_url")
                count = int(request.form.get("commit_count"))
                commits = []

                for i in range(count):
                    message = request.form.get(f"commit_msg_{i}")
                    reason = request.form.get(f"reason_{i}")
                    file_count = int(request.form.get(f"file_count_{i}"))
                    files = []

                    for j in range(file_count):
                        path = request.form.get(f"file_{i}_{j}")
                        added = request.form.get(f"added_{i}_{j}", "").split("\n")
                        removed = request.form.get(f"removed_{i}_{j}", "").split("\n")
                        files.append({
                            "file_path": path,
                            "added_lines": added,
                            "removed_lines": removed
                        })

                    commits.append({
                        "message": message,
                        "reason": reason,
                        "files_changed": files
                    })

                summary = {
                    "metadata": {
                        "title": "Edited Reasons",
                        "author": "-",
                        "state": "-",
                        "url": pr_url
                    },
                    "commits": commits
                }

                save_summary_to_json(summary)

        except Exception as e:
            error = str(e)

    return render_template("index.html", summary=summary, error=error)


def parse_pr_url(url):
    parts = url.strip().split("/")
    repo = "/".join(parts[3:5])
    pr_number = int(parts[-1])
    return repo, pr_number


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)