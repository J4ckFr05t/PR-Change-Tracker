from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for, send_file, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from github_utils import get_pr_data
from save_to_json import save_summary_to_json
from dotenv import load_dotenv
from celery.result import AsyncResult
from tasks import analyze_pr_task
from celery_worker import celery
import os
import re
import io
import pandas as pd
import json

app = Flask(__name__)

load_dotenv()
#github_token = os.getenv("GITHUB_API_KEY")

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)  # Unique ID
    email = db.Column(db.String(150), unique=True, nullable=False)  # User's email (used for login)
    password = db.Column(db.String(150), nullable=False)  # Hashed password
    github_api_token = db.Column(db.String(255))
    google_api_token = db.Column(db.String(255))

    def __repr__(self):
        return f"<User {self.email}>"
    
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered. Please log in.", "warning")
            return redirect(url_for("login"))

        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash("Signup successful!", "success")
        return redirect(url_for("user_dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.pop('_flashes', None)  # 👈 Clear existing messages first

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("user_dashboard"))
        else:
            flash("Invalid email or password.", "danger")

    return render_template("login.html")

@app.route("/dashboard")
@login_required
def user_dashboard():
    return render_template("user.html", user_email=current_user.email)

@app.route("/update_password", methods=["POST"])
@login_required
def update_password():
    current = request.form.get("current_password")
    new = request.form.get("new_password")
    confirm = request.form.get("confirm_password")

    if not check_password_hash(current_user.password, current):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("user_dashboard"))

    if new != confirm:
        flash("New passwords do not match.", "error")
        return redirect(url_for("user_dashboard"))

    current_user.password = generate_password_hash(new)
    db.session.commit()
    flash("Password updated successfully!", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/update_github_token", methods=["POST"])
@login_required
def update_token():
    token = request.form.get("github_api_token")

    if not token or len(token) < 10:
        flash("Invalid GitHub token.", "error")
        return redirect(url_for("user_dashboard"))

    current_user.github_api_token = token
    db.session.commit()
    flash("GitHub token updated successfully!", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/update_google_token", methods=["POST"])
@login_required
def update_google_token():
    token = request.form.get("google_api_token")

    if not token or len(token) < 10:
        flash("Invalid Google token.", "error")
        return redirect(url_for("user_dashboard"))

    current_user.google_api_token = token
    db.session.commit()
    flash("Google token updated successfully!", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/summarize", methods=["POST"])
@login_required
def summarize():
    data = request.get_json()
    print("Received data:", data)

    pr_url = data.get("pr_url")
    if not pr_url:
        return jsonify({"error": "Missing PR URL"}), 400

    try:
        print("Parsing PR URL...")
        repo, pr_number = parse_pr_url(pr_url)
        print("Parsed repo:", repo, "PR number:", pr_number)

        # print("[DEBUG] Current User Google Token:", current_user.google_api_token)
        # print("[DEBUG] Current User GitHub Token:", current_user.github_api_token)

        user_github_token = current_user.github_api_token
        pr_data = get_pr_data(repo, pr_number, user_github_token)
        print("Fetched PR data.")

        task = analyze_pr_task.apply_async(args=[{
            "pr_data": pr_data,
            "url": pr_url,
            "google_token": current_user.google_api_token
        }])
        print("Task ID:", task.id)

        return jsonify({"task_id": task.id})

    except Exception as e:
        print("Error during summarization:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/result/<task_id>")
def show_result(task_id):
    task = AsyncResult(task_id, app=celery)
    if task.state == "SUCCESS":
        return render_template("index.html", summary=task.result)
    elif task.state in ["PENDING", "STARTED", "PROGRESS"]:
        return render_template("index.html", task_id=task.id)
    else:
        return render_template("index.html", error="Task failed or was canceled.")

# @app.route("/", methods=["GET", "POST"])
# @login_required
# def index():
#     summary = None
#     error = None
#     action = None
#     task_id = None

#     if request.method == "POST":
#         action = request.form.get("action")

#         try:
#             if action == "analyze":
#                 pr_url = request.form.get("pr_url")
#                 repo, pr_number = parse_pr_url(pr_url)

#                 pr_data = get_pr_data(repo, pr_number, github_token)

#                 # Call the background Celery task
#                 task = analyze_pr_task.apply_async(args=[{
#                     "pr_data": pr_data,
#                     "url": pr_url
#                 }])
#                 task_id = task.id

#                 return render_template("index.html", task_id=task_id)  # UI should poll using this

#             elif action == "save":
#                 pr_url = request.form.get("pr_url")
#                 count = int(request.form.get("commit_count"))
#                 commits = []

#                 for i in range(count):
#                     message = request.form.get(f"commit_msg_{i}")
#                     reason = request.form.get(f"reason_{i}")
#                     file_count = int(request.form.get(f"file_count_{i}"))
#                     files = []

#                     for j in range(file_count):
#                         path = request.form.get(f"file_{i}_{j}")
#                         added = request.form.get(f"added_{i}_{j}", "").split("\n")
#                         removed = request.form.get(f"removed_{i}_{j}", "").split("\n")
#                         files.append({
#                             "file_path": path,
#                             "added_lines": added,
#                             "removed_lines": removed
#                         })

#                     commits.append({
#                         "message": message,
#                         "reason": reason,
#                         "files_changed": files
#                     })

#                 summary = {
#                     "metadata": {
#                         "title": "Edited Reasons",
#                         "author": "-",
#                         "state": "-",
#                         "url": pr_url
#                     },
#                     "commits": commits
#                 }

#                 save_summary_to_json(summary)

#         except Exception as e:
#             error = str(e)

#     saved = action == "save" and not error
#     return render_template("index.html", summary=summary, error=error, saved=saved, task_id=task_id)

@app.route("/")
def root_redirect():
    if current_user.is_authenticated:
        return redirect(url_for("user_dashboard"))
    else:
        return redirect(url_for("login"))

@app.route("/task_status/<task_id>")
def task_status(task_id):
    task = AsyncResult(task_id, app=celery)

    # print(f"Task {task_id} state: {task.state}")
    # print("Meta:", task.info)

    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'progress': 0
        }
    elif task.state == 'PROGRESS':
        progress = task.info or {}
        current = progress.get('current', 0)
        total = progress.get('total', 1)
        response = {
            'state': task.state,
            'progress': int((current / total) * 100),
            'details': progress.get('status', '')
        }
    elif task.state == 'SUCCESS':
        response = {
            'state': task.state,
            'progress': 100,
            'result': task.result
        }
    else:
        response = {
            'state': task.state,
            'error': str(task.info)
        }

    return jsonify(response)


@app.route("/download_excel", methods=["POST"])
def download_excel():
    try:
        pr_url = request.form.get("pr_url", "")
        count = int(request.form.get("commit_count"))
        rows = []

        match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
        if match:
            repo = match.group(1).replace("/", "_")
            pr_number = match.group(2)
        else:
            repo = "unknown_repo"
            pr_number = "unknown_pr"

        for i in range(count):
            reason = request.form.get(f"reason_{i}")
            file_count = int(request.form.get(f"file_count_{i}"))

            for j in range(file_count):
                file_name = request.form.get(f"file_{i}_{j}")
                rows.append({
                    "File Name": file_name,
                    "Reason to Change": reason
                })

        df = pd.DataFrame(rows)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Summary")

        output.seek(0)
        filename = f"diffsage_{repo}_pr{pr_number}.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        return f"Error creating Excel file: {str(e)}", 500


def parse_pr_url(url):
    parts = url.strip().split("/")
    repo = "/".join(parts[3:5])
    pr_number = int(parts[-1])
    return repo, pr_number


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Automatically create tables if they don't exist
    app.run(host="0.0.0.0", port=3000, debug=True)
