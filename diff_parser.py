from unidiff import PatchSet
from io import StringIO

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

    return result