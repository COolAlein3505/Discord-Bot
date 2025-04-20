<div align="center">
  <img height="340" src="https://kingsoccertips.com/wp-content/uploads/2024/02/cricket-betting-strategy.jpg" alt="Project Banner" />
</div>

---

<div align="center">
  <a href="#"><img src="https://img.shields.io/static/v1?message=LinkedIn&logo=linkedin&label=&color=0077B5&logoColor=white&labelColor=&style=for-the-badge" height="25" alt="LinkedIn" /></a>
  <a href="#"><img src="https://img.shields.io/static/v1?message=Youtube&logo=youtube&label=&color=FF0000&logoColor=white&labelColor=&style=for-the-badge" height="25" alt="YouTube" /></a>
  <a href="#"><img src="https://img.shields.io/static/v1?message=Twitter&logo=twitter&label=&color=1DA1F2&logoColor=white&labelColor=&style=for-the-badge" height="25" alt="Twitter" /></a>
</div>

---

<div align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=COolAlein3505.COolAlein3505" alt="visitor badge" />
</div>

---

<h1 align="center">🏏 <PROJECT_NAME><br>by <TEAM_NAME></h1>

---

### 🚀 Overview

**<PROJECT_NAME>** is a Discord-based prediction-market arcade for live IPL matches.  
Users wager virtual points on simple yes/no questions (e.g., *“Will Team X score ≥ Y runs in the next over?”*) by buying & selling shares.

Market prices are driven by both **real-time data** and **supply & demand**. The experience is fully integrated into Discord, creating a fun and competitive environment for cricket fans.

---

### 🎯 Key Features

- **🧠 Auto‑Generated Markets**  
  - Bot dynamically creates new yes/no questions during a match.  
  - Example: *“Will the team score ≥ 48 runs by 5.0 overs?”*

- **📈 Real‑Time Data**  
  - Fetches ball-by-ball scores and win probabilities from a live Cricket API.  
  - Markets adjust instantly with new match updates.

- **💰 Virtual Points Economy**  
  - Every user starts with 20 points.  
  - ✅ Correct prediction → earn stake + profit.  
  - ❌ Wrong prediction → lose stake.

- **📊 Dynamic Pricing Model**  
  - Prices adapt to trade volume and live win-probability.  
  - Example: Heavy YES demand → YES price ↑, NO price ↓.

- **🏅 Tiered Ranking System**  
  - Levels from *Newbie → Pupil → Specialist → Expert → Candidate Master → ...*  
  - Ranks reflect user prediction accuracy and are synced with Discord roles.

- **🤖 Full Discord Integration**  
  - **Admin Commands**: `!create_question`, `!resolve`  
  - **User Commands**: `!list_questions`, `!market`, `!buy`, `!sell`, `!balance`, `!check_rank`

---

### 🛠 Tech Stack

- **Language:** Python 3.x  
- **Discord Bot:** `discord.py`  
- **Live Data:** Cricket API (ball-by-ball + win probabilities)  
- **Persistence:** CSV-based logging for trades and balances  
- **Deployment:** Docker on AWS / VM

---

### ⚙️ Prerequisites

- Python 3.8 or higher  
- A valid Discord bot token  
- Cricket API key (for live match data)

---

### 🔧 Installation & Setup

Follow the steps below to set up and run the bot:

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/your-repo-name.git
cd your-repo-name

# 2. Create & activate a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# 3. Install the dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Open the .env file and add your tokens
# DISCORD_TOKEN=your_bot_token
# CRICKET_API_KEY=your_api_key

# 5. Start the bot
python bot.py
