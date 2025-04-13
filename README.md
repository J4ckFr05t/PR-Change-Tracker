# DiffSage 🧠🔍

**DiffSage** is a web-based tool for analyzing GitHub Pull Requests with precision. It summarizes commit-level diffs, allows human-in-the-loop reasoning for code changes, and lets users export the results to Excel for audits, reviews, or documentation.

---

## 🖼️ UI Preview

Here’s a demo:

![DiffSage Demo](static/demo.gif)

---

## 🚀 Features

- 🔗 Input any **GitHub Pull Request URL**
- 📆 Retrieves PR metadata, commits, and file-level diffs using the GitHub API
- 📝 Add or edit **reasons for each code change** per commit
- 📁 Supports added, removed, and modified lines for each file
- 📄 Export a clean Excel report with:
  - File Name
  - Reason to Change
- 🍗 Dark Mode Toggle for comfortable UI

---

## 🧰 Tech Stack

- **Flask** – Backend framework
- **Jinja2** – For rendering HTML templates
- **GitHub API** – For fetching PR and commit data
- **Python + Pandas + xlsxwriter** – Excel report generation
- **HTML/CSS/JS** – UI/UX and client-side interactivity
- **Docker** – Containerized deployment

---

## ⚙️ Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/diffsage.git
cd diffsage
```

### 2. Set up Environment Variables (.env)

```env
GITHUB_API_KEY=your_personal_access_token_here
GOOGLE_API_KEY=your_personal_access_token_here
```

---

### 3. Option A: Local Run (with Python)

#### Create & activate virtual environment (optional but recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

#### Install dependencies

```bash
pip install -r requirements.txt
```

#### Run the Flask app

```bash
python app.py
```

#### Start the Redis
Windows
##### Installing via WSL (Windows Subsystem for Linux)
```bash
sudo apt update
sudo apt install redis-server
redis-server
```

macOS
##### Installing via Homebrew
```bash
brew install redis
brew services start redis
```

(Ubuntu/Debian)
##### Installing via APT
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
```

#### Start the Celery Worker

```bash
celery -A celery_worker.celery worker --loglevel=info
```

App runs at: [http://localhost:3000](http://localhost:3000)

---

### 3. Option B: Run with Docker 🐳

#### Build Docker image

```bash
docker compose up -d --build
```

> Visit the app at: [http://localhost:3000](http://localhost:3000)

---

## 📄 Usage Workflow

1. Paste a GitHub PR URL (e.g., `https://github.com/user/repo/pull/42`)
2. View parsed commit messages and file diffs
3. Add/edit reasons for each change
4. Click "💾 Download Excel"
5. Excel filename will include `repo` and `PR number`, e.g.:  
   `diffsage_openai_gym_pr42.xlsx`

---

## 📆 Folder Structure

```
DiffSage/
├── app.py                 # Main Flask application
├── celery_worker.py       # Celery worker setup
├── tasks.py               # Celery task definitions
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image configuration
├── docker-compose.yml     # Multi-container orchestration
├── templates/
│   └── index.html         # HTML template for the frontend
├── static/                # Static files (CSS, JS, images)
├── README.md              # Project documentation
└── .env                   # Environment variables (optional)
```

---

## 👨‍💼 Author

Built by J4ckFr05t.  
Security-focused. Dev-friendly. Audit-ready.  
Pull requests and feedback are welcome!

---

## 📜 License

This project is licensed under the MIT License.
