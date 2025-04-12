import time
import copy
import queue
import threading
import google.generativeai as genai
from dotenv import load_dotenv
import os
from unidiff import PatchSet
from io import StringIO
import concurrent.futures
import logging
import re
import json
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Gemini client with API Key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Load the model
model = genai.GenerativeModel("gemini-2.0-flash")

# Rate limiter class using token bucket algorithm
class RateLimiter:
    def __init__(self, rpm_limit=30, tpm_limit=1000000):
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.request_tokens = rpm_limit
        self.token_tokens = tpm_limit
        self.last_request_refill = time.time()
        self.last_token_refill = time.time()
        self.lock = threading.Lock()
        self.quota_exceeded = False
        self.quota_reset_time = None
        self.quota_lock = threading.Lock()

    def _refill_tokens(self):
        now = time.time()
        elapsed_seconds = now - self.last_request_refill
        new_request_tokens = elapsed_seconds * (self.rpm_limit / 60)
        elapsed_seconds_tokens = now - self.last_token_refill
        new_token_tokens = elapsed_seconds_tokens * (self.tpm_limit / 60)
        with self.lock:
            self.request_tokens = min(self.rpm_limit, self.request_tokens + new_request_tokens)
            self.token_tokens = min(self.tpm_limit, self.token_tokens + new_token_tokens)
            self.last_request_refill = now
            self.last_token_refill = now

    def set_quota_exceeded(self, retry_timestamp):
        # Convert the timestamp to datetime
        retry_time = datetime.utcfromtimestamp(retry_timestamp)
        with self.quota_lock:
            self.quota_exceeded = True
            self.quota_reset_time = retry_time
            logger.warning(f"Quota exceeded. Pausing all requests until {self.quota_reset_time.strftime('%H:%M:%S')}")


    def check_quota_status(self):
        with self.quota_lock:
            if not self.quota_exceeded:
                return True
            if datetime.now() >= self.quota_reset_time:
                logger.info("Quota reset time reached. Resuming operations.")
                self.quota_exceeded = False
                return True
            return False

    def acquire(self, tokens_needed=1):
        if not self.check_quota_status():
            reset_in = (self.quota_reset_time - datetime.now()).total_seconds()
            logger.debug(f"Still in quota exceeded state. Reset in {reset_in:.1f}s")
            return False
        while True:
            self._refill_tokens()
            with self.lock:
                if self.request_tokens >= 1 and self.token_tokens >= tokens_needed:
                    self.request_tokens -= 1
                    self.token_tokens -= tokens_needed
                    return True
            with self.lock:
                request_wait = (1 - self.request_tokens) * (60 / self.rpm_limit) if self.request_tokens < 1 else 0
                token_wait = (tokens_needed - self.token_tokens) * (60 / self.tpm_limit) if self.token_tokens < tokens_needed else 0
                wait_time = max(request_wait, token_wait, 0.1)
            logger.debug(f"Rate limit backpressure. Waiting {wait_time:.2f}s")
            time.sleep(wait_time)

# --- Retry Queue with Proper Task Done ---
class RetryQueue:
    def __init__(self, max_retries=5):
        self.queue = queue.PriorityQueue()
        self.max_retries = max_retries
        self.lock = threading.Lock()
        self.active_items = 0
        self.condition = threading.Condition(self.lock)

    def add(self, priority, item, retry_count=0, next_retry=None):
        if next_retry is None:
            next_retry = time.time()
        with self.lock:
            self.queue.put((next_retry, priority, retry_count, item))
            self.active_items += 1
            self.condition.notify_all()

    def get(self, block=True, timeout=None):
        with self.lock:
            while True:
                if self.queue.empty():
                    if not block:
                        return None
                    if timeout is not None:
                        if not self.condition.wait(timeout=timeout):
                            return None
                    else:
                        self.condition.wait()
                    continue
                next_retry, priority, retry_count, item = self.queue.queue[0]
                if time.time() >= next_retry:
                    return self.queue.get()
                if not block:
                    return None
                wait_time = min(next_retry - time.time(), 0.5) if timeout is None else min(next_retry - time.time(), timeout, 0.5)
                if wait_time > 0:
                    self.condition.wait(timeout=wait_time)

    def task_done(self):
        with self.lock:
            self.active_items -= 1
            self.condition.notify_all()

    def all_done(self):
        with self.lock:
            return self.active_items == 0

# --- Supporting Functions ---
def extract_retry_delay(error_message):
    try:
        # Look for a retry_delay field in the response
        match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)\s*\}', str(error_message))
        if match:
            return int(match.group(1))
        try:
            # Attempt to parse a JSON response to extract retry delay
            error_json = json.loads(error_message)
            if 'retry_delay' in error_json and 'seconds' in error_json['retry_delay']:
                return int(error_json['retry_delay']['seconds'])
        except (json.JSONDecodeError, TypeError) as json_error:
            logger.warning(f"Failed to parse retry delay from error message: {json_error}")

    except Exception as e:
        logger.warning(f"Failed to extract retry delay: {e}")
    
    # Return a default retry delay (e.g., 60 seconds) if retry delay is not found
    logger.warning("Using default retry delay of 60 seconds.")
    return 60  # Default retry delay


def estimate_tokens(text):
    return len(text) // 4 + 1

def summarize_change(message, added_lines, removed_lines, rate_limiter):
    prompt = (
        "Here is a code change. Based on the added and removed lines, and the commit messages, "
        "provide a brief natural language description of what was changed and why. Be concise but informative.\n\n"
        f"Commit message(s): {message}\n\n"
        f"Added lines:\n" + "\n".join(added_lines or []) + "\n\n" +
        f"Removed lines:\n" + "\n".join(removed_lines or [])
    )
    est_tokens = estimate_tokens(prompt) + 200
    if not rate_limiter.acquire(est_tokens):
        raise Exception("Quota exceeded, request queued for retry")
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=200
            )
        )
        return response.text.strip()

    except Exception as e:
        # Log the full error response
        error_msg = str(e)
        logger.error(f"API call failed with error: {error_msg}")
        
        # If the error is related to quota limits (HTTP 429), log the retry delay and reset status
        if "429" in error_msg and "quota" in error_msg.lower():
            retry_delay = extract_retry_delay(error_msg)
            rate_limiter.set_quota_exceeded(retry_delay)
            logger.error(f"Quota exceeded. Retrying after {retry_delay} seconds.")
        
        # Log more detailed information about the exception
        logger.error(f"Detailed exception: {e}")
        
        raise e

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

def process_item(item, index, total, rate_limiter, retry_queue=None):
    logger.info(f"Processing item {index+1}/{total}...")
    file_change = item["files_changed"][0]
    if file_change["change_type"] == "modified":
        try:
            summary = summarize_change(
                message=item["message"],
                added_lines=file_change["added_lines"],
                removed_lines=file_change["removed_lines"],
                rate_limiter=rate_limiter
            )
            logger.info(f"Completed {index+1}/{total}.")
            return summary
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            if retry_queue is not None:
                retry_delay = extract_retry_delay(str(e))
                next_retry = time.time() + retry_delay
                retry_queue.add(priority=index, item=item, next_retry=next_retry)
                logger.info(f"Item {index+1}/{total} queued for retry in {retry_delay}s")
            return None
    else:
        logger.info(f"Skipped {index+1}/{total} (not modified).")
        return ""

def parse_diff_by_commit(commits, max_workers=5, max_retries=5):
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
            is_new_file = file.is_added_file and len(removed) == 0 and len(added) > 0
            commit_entry["files_changed"].append({
                "file_path": file.path,
                "change_type": change_type,
                "added_lines": added,
                "removed_lines": removed,
                "is_new_file": is_new_file
            })
        result.append(commit_entry)

    exploded = []
    for entry in result:
        for file_change in entry.get('files_changed', []):
            exploded.append({
                'message': entry.get('message'),
                'files_changed': [file_change]
            })

    change_type_priority = {'deleted': 0, 'added': 1, 'modified': 2}
    exploded.sort(key=lambda e: change_type_priority.get(e['files_changed'][0]['change_type'], 99))
    grouped_data = regroup_by_file_path(exploded)

    total_items = len(grouped_data)

    rate_limiter = RateLimiter(rpm_limit=30, tpm_limit=1000000)
    retry_queue = RetryQueue(max_retries=max_retries)
    results = {i: None for i in range(total_items)}
    item_retries = {i: 0 for i in range(total_items)}
    processing_complete = threading.Event()
    retry_thread_exception = None

    def retry_worker():
        nonlocal retry_thread_exception
        try:
            while not processing_complete.is_set():
                queue_item = retry_queue.get(block=True, timeout=0.5)
                if queue_item is None:
                    if all(v is not None for v in results.values()) and retry_queue.all_done():
                        logger.info("All items processed, retry worker finishing")
                        break
                    continue
                retry_time, priority, retry_count, item = queue_item
                index = priority
                item_retries[index] += 1
                try:
                    if item_retries[index] > max_retries:
                        results[index] = f"Error: Exceeded maximum retry attempts ({max_retries})"
                        grouped_data[index]["summary"] = results[index]
                        logger.warning(f"Item {index+1}/{total_items} exceeded max retries")
                    elif not rate_limiter.check_quota_status():
                        next_retry = rate_limiter.quota_reset_time.timestamp()
                        retry_queue.add(priority=index, item=item, retry_count=retry_count+1, next_retry=next_retry)
                        logger.warning(f"Item {index+1}/{total_items} queued for retry due to quota exceeded. Retry after {next_retry}")
                        time.sleep(1)
                        continue
                    else:
                        summary = process_item(item, index, total_items, rate_limiter)
                        if summary is not None:
                            results[index] = summary
                            grouped_data[index]["summary"] = summary
                            logger.info(f"Retry successful for item {index+1}/{total_items}")
                        else:
                            logger.info(f"Item {index+1}/{total_items} was re-queued during retry")
                            continue
                except Exception as e:
                    retry_delay = min(60 * (2 ** retry_count), 300)
                    next_retry = time.time() + retry_delay
                    retry_queue.add(priority=index, item=item, retry_count=retry_count+1, next_retry=next_retry)
                    logger.error(f"Retry failed for item {index+1}/{total_items}: {e}")
                finally:
                    retry_queue.task_done()
        except Exception as e:
            retry_thread_exception = e
            logger.error(f"Retry worker thread crashed: {e}")


    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            retry_thread = threading.Thread(target=retry_worker)
            retry_thread.daemon = True
            retry_thread.start()

            future_to_index = {}
            for i, item in enumerate(grouped_data):
                file_change = item["files_changed"][0]
                if file_change["change_type"] != "modified":
                    results[i] = ""
                    grouped_data[i]["summary"] = ""
                    continue
                future = executor.submit(process_item, item, i, total_items, rate_limiter, retry_queue)
                future_to_index[future] = i

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    summary = future.result()
                    if summary is not None:
                        results[index] = summary
                        grouped_data[index]["summary"] = summary
                except Exception as exc:
                    logger.error(f"Item {index+1}/{total_items} generated an exception: {exc}")
                    results[index] = f"Error: Exception occurred - {exc}"

            missing_results = [i for i, v in results.items() if v is None]
            if missing_results:
                logger.info(f"Waiting for {len(missing_results)} items to complete via retry queue")
                max_wait = 600
                start_wait = time.time()
                while time.time() - start_wait < max_wait:
                    if retry_thread_exception is not None:
                        logger.error(f"Retry thread crashed: {retry_thread_exception}")
                        break
                    if all(v is not None for v in results.values()):
                        logger.info("All items completed successfully")
                        break
                    if retry_queue.all_done():
                        logger.info("Retry queue is empty but some items still missing results")
                        for i in missing_results:
                            results[i] = f"Error: Failed to process after {max_retries} attempts"
                            grouped_data[i]["summary"] = results[i]
                        break
                    logger.info(f"Still waiting for {len([i for i, v in results.items() if v is None])} items to complete")
                    time.sleep(5)

                for i in [i for i, v in results.items() if v is None]:
                    results[i] = "Error: Timeout waiting for processing to complete"
                    grouped_data[i]["summary"] = results[i]

            processing_complete.set()
            retry_thread.join(timeout=10)
    except Exception as e:
        logger.error(f"Error in main processing: {e}")
        for i, v in results.items():
            if v is None:
                results[i] = f"Error: Processing failed - {str(e)}"
                grouped_data[i]["summary"] = results[i]

    for i, item in enumerate(grouped_data):
        if "summary" not in item or item["summary"] is None:
            item["summary"] = "Error: Processing incomplete"
    logger.info("All processing complete, returning results")
    return grouped_data
