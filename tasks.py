from celery import Celery
from celery_worker import celery
from diff_parser import parse_diff_by_commit  # existing function
import time

@celery.task(bind=True)
def analyze_pr_task(self, pr_commits_and_metadata):
    try:
        pr_data = pr_commits_and_metadata["pr_data"]
        commits = pr_data["commits"]
        google_token = pr_commits_and_metadata.get("google_token")
        #print("[DEBUG] Google token in Celery task:", google_token)

        # Analyze diffs (with progress tracking)
        grouped_data = parse_diff_by_commit(commits, self, google_token=google_token)

        # Full summary (matches original code)
        summary = {
            "metadata": {
                "title": pr_data["title"],
                "author": pr_data["author"],
                "state": pr_data["state"],
                "url": pr_commits_and_metadata.get("url", "-")
            },
            "commits": grouped_data
        }

        return summary

    except Exception as e:
        self.update_state(state="FAILURE", meta={"exc": str(e)})
        raise e
