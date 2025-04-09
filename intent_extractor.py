import re

def extract_commit_reasons(commit_messages):
    reasons = []
    for msg in commit_messages:
        cleaned = msg.strip().split("\n")[0]  # Use subject line
        reason = classify_reason(cleaned)
        reasons.append({"message": cleaned, "category": reason})
    return reasons

def classify_reason(message):
    message = message.lower()
    if "fix" in message or "bug" in message:
        return "Bug Fix"
    if "refactor" in message:
        return "Refactor"
    if "add" in message or "feature" in message:
        return "Feature"
    if "remove" in message or "delete" in message:
        return "Removal"
    if "doc" in message or "readme" in message:
        return "Documentation"
    if "test" in message:
        return "Testing"
    return "Other"