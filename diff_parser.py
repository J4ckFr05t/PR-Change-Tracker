from unidiff import PatchSet
from io import StringIO
import json
import copy

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

def parse_diff_by_commit(commits):
    result = []

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

            # Flag to indicate this is a newly added file
            is_new_file = file.is_added_file and len(removed) == 0 and len(added) > 0

            commit_entry["files_changed"].append({
                "file_path": file.path,
                "change_type": change_type,
                "added_lines": added,
                "removed_lines": removed,
                "is_new_file": is_new_file
            })

        result.append(commit_entry)

    change_type_priority = {
        'deleted': 0,
        'added': 1,
        'modified': 2
    }

    exploded = []
    for entry in result:
        for file_change in entry.get('files_changed', []):
            exploded.append({
                'message': entry.get('message'),
                'files_changed': [file_change]  # keep as single-element list
            })

    # Sort based on custom priority
    exploded.sort(key=lambda e: change_type_priority.get(e['files_changed'][0]['change_type'], 99))
    
    grouped_data = regroup_by_file_path(exploded)

    return grouped_data