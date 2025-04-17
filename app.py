from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for, send_file, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from github_utils import get_pr_data
import google.generativeai as genai
from celery.result import AsyncResult
from tasks import analyze_pr_task
from celery_worker import celery
import os
import re
import io
import pandas as pd
import json

app = Flask(__name__)

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
    
def validate_google_token(token):
    try:
        genai.configure(api_key=token)
        model = genai.GenerativeModel("gemini-2.0-flash")
        _ = model.generate_content("Hello", generation_config=genai.types.GenerationConfig(
            temperature=0.1, max_output_tokens=10
        ))
        return True
    except Exception as e:
        print("[Token Validation Error]", e)
        return False
    
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
    #session.pop('_flashes', None)  # 👈 Clear existing messages first

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
    #print("Received data:", data)

    pr_url = data.get("pr_url")
    if not pr_url:
        return jsonify({"error": "Missing PR URL"}), 400
    
    if not current_user.github_api_token or not current_user.google_api_token:
        return jsonify({
            "error": "Both GitHub and Google API tokens are required. Please set them up in your Account Info."
        }), 400
    
    if not validate_google_token(current_user.google_api_token):
        return jsonify({"error": "Invalid Google token. Please make sure your token is correct and try again."}), 400


    try:
        print("Parsing PR URL...")
        user_github_token = current_user.github_api_token

        parsed = parse_github_url(pr_url)
        pr_data = get_pr_data(parsed, current_user.github_api_token)

        if "error" in pr_data:
            print(f"[ERROR] GitHub API returned an error: {pr_data['error']}")
            return jsonify({"error": "There was an issue with your GitHub token. Please make sure your token is correct and try again."}), 400  # Stop execution and return the error
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


import re

def parse_github_url(url):
    """
    Parses a GitHub Pull Request or Compare URL and returns a dict with type info.
    """
    url = url.strip()
    pr_pattern = r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    compare_pattern = r"https://github\.com/([^/]+)/([^/]+)/compare/(.+)\.\.\.(.+)"

    pr_match = re.match(pr_pattern, url)
    if pr_match:
        return {
            "type": "pr",
            "repo": f"{pr_match.group(1)}/{pr_match.group(2)}",
            "pr_number": int(pr_match.group(3))
        }

    compare_match = re.match(compare_pattern, url)
    if compare_match:
        return {
            "type": "compare",
            "repo": f"{compare_match.group(1)}/{compare_match.group(2)}",
            "base": compare_match.group(3),
            "head": compare_match.group(4)
        }

    raise ValueError("Unsupported or invalid GitHub URL.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Automatically create tables if they don't exist
    app.run(host="0.0.0.0", port=3000, debug=True)
