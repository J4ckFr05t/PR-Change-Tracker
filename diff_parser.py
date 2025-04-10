from unidiff import PatchSet
from io import StringIO
import json

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

    # Print few entries for verification
    for e in exploded:
        print(entry["files_changed"][0]['change_type'])

    return exploded