from unidiff import PatchSet
from io import StringIO
import json
import copy
import google.generativeai as genai
import os
import time

# Function to call Gemini and generate summary with retry logic
def summarize_change_with_retry(message, added_lines, removed_lines, google_token=None, retries=3):
    #print("[DEBUG] Google token in summarize_change_with_retry:", google_token)

    # ✅ Configure token ONCE
    genai.configure(api_key=google_token)

    model = genai.GenerativeModel("gemini-2.0-flash")

    attempt = 0
    while attempt < retries:
        try:
            prompt = (
                "Here is a code change. Based on the added and removed lines, and the commit messages, "
                "provide a brief natural language description of what was changed and why. Be concise but informative.\n\n"
                f"Commit message(s): {message}\n\n"
                f"Added lines:\n" + "\n".join(added_lines or []) + "\n\n" +
                f"Removed lines:\n" + "\n".join(removed_lines or [])
            )

            response = genai.GenerativeModel("gemini-2.0-flash").generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=200
                )
            )
            return response.text.strip()

        except Exception as e:
            error_message = str(e)
            print(error_message)

            if "429" in error_message and "retry_delay" in error_message:
                match = re.search(r'retry_delay\s*{\s*seconds\s*:\s*(\d+)', error_message)
                if match:
                    retry_delay = int(match.group(1))
                    print(f"Quota exceeded. Retrying in {retry_delay + 1} seconds...")
                    time.sleep(retry_delay + 1)
                    attempt += 1
                    continue
                else:
                    print("Couldn't parse retry delay.")
                    break
            else:
                return f"Error generating summary: {e}"

    # 🔁 Final retry after 1 min, must include google_token
    print("Retries exhausted. Waiting 1 minute before retrying once more...")
    time.sleep(60)
    return summarize_change_with_retry(
        message, added_lines, removed_lines,
        google_token=google_token, retries=1
    )

# Group changes by file path
def regroup_by_file_path(data, message_separator=" || ", line_separator="---"):
    grouped = {}

    for entry in data:
        message = entry["message"]
        for file in entry["files_changed"]:
            path = file["file_path"]
            if path not in grouped:
                grouped[path] = {
                    "message": message,
                    "files_changed": [{
                        "file_path": path,
                        "change_type": file["change_type"],
                        "is_new_file": file["is_new_file"],
                        "added_lines": copy.deepcopy(file["added_lines"]),
                        "removed_lines": copy.deepcopy(file["removed_lines"])
                    }]
                }
            else:
                grouped[path]["message"] += message_separator + message
                file_changed = grouped[path]["files_changed"][0]

                if file_changed["added_lines"] and file["added_lines"]:
                    file_changed["added_lines"].append(line_separator)
                file_changed["added_lines"].extend(file["added_lines"])

                if file_changed["removed_lines"] and file["removed_lines"]:
                    file_changed["removed_lines"].append(line_separator)
                file_changed["removed_lines"].extend(file["removed_lines"])

    return list(grouped.values())

# Main parsing function
def parse_diff_by_commit(commits,  task=None, google_token=None):
    result = []
    #print("[DEBUG] Google token in diff_parser:", google_token)
    for commit in commits:
        commit_entry = {
            "message": commit["message"],
            "files_changed": []
        }

        patch_set = PatchSet(StringIO(commit["diff"]))
        for file in patch_set:
            added = [line.value.strip() for hunk in file for line in hunk if line.is_added]
            removed = [line.value.strip() for hunk in file for line in hunk if line.is_removed]

            if file.is_added_file:
                change_type = "added"
            elif file.is_removed_file:
                change_type = "deleted"
            else:
                change_type = "modified"

            is_new_file = file.is_added_file and len(removed) == 0 and len(added) > 0

            commit_entry["files_changed"].append({
                "file_path": file.path,
                "change_type": change_type,
                "added_lines": added,
                "removed_lines": removed,
                "is_new_file": is_new_file
            })

        result.append(commit_entry)

    # Flatten to per-file level
    exploded = []
    for entry in result:
        for file_change in entry.get('files_changed', []):
            exploded.append({
                'message': entry.get('message'),
                'files_changed': [file_change]  # single-element list
            })

    # Sort based on custom priority
    change_type_priority = {
        'deleted': 0,
        'added': 1,
        'modified': 2
    }
    exploded.sort(key=lambda e: change_type_priority.get(e['files_changed'][0]['change_type'], 99))

    # Group by file path
    grouped_data = regroup_by_file_path(exploded)

    print("Number of Files to be process:", len(grouped_data))
    file_count = len(grouped_data)

    # Add Gemini summaries
    for index, item in enumerate(grouped_data, start=1):
        if task:
            progress_meta = {
                'current': index,
                'total': file_count,
                'status': f'Processed {index} of {file_count}'
            }
            print("Progress update:", progress_meta)
            task.update_state(state='PROGRESS', meta=progress_meta)

        file_change = item["files_changed"][0]
        item["summary"] = summarize_change_with_retry(
            message=item["message"],
            added_lines=file_change["added_lines"],
            removed_lines=file_change["removed_lines"],
            google_token=google_token
        )

        if index % 15 == 0:
            print(f"Processed {index}/{file_count} items. Sleeping for 60 seconds to avoid hitting rate limits.")
            time.sleep(60)
        else:
            print(f"Processed {index}/{file_count} items.")

    return grouped_data