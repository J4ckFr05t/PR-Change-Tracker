import json
import datetime

def save_summary_to_json(summary, output_path="output_changes.json"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"changes_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)

    print(f"Saved changes to {filename}")