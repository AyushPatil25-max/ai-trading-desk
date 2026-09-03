# AI Trading Desk - Clone and Run Guide

## OVERVIEW

This guide describes how to clone and run the AI Trading Desk project locally. The environment is designed primarily for Windows. 
**Real-money trading is disabled by default.**

## 1. PREREQUISITES

- Git
- Python 3.10+
- (Optional) node.js if using any node-based build tools in the future, though currently frontend is static.

## 2. CLONE

Open PowerShell or Command Prompt and clone the repository:

```powershell
git clone https://github.com/AyushPatil25-max/ai-trading-desk.git
cd ai-trading-desk
```

## 3. ENVIRONMENT

Create a Python virtual environment:

```powershell
python -m venv venv
```

Activate the virtual environment:

```powershell
.\venv\Scripts\activate
```

## 4. DEPENDENCIES

Install the required Python dependencies:

```powershell
pip install -r requirements.txt
```

## 5. CONFIGURATION

Copy the example environment variables file and configure it:

```powershell
Copy-Item .env.example .env
```
Open `.env` in a text editor and fill in your details.

**Important Defaults (Safe Mode):**
```
LIVE_EXECUTION_ENABLED=false
DHAN_ENABLED=true
DHAN_CLIENT_ID=your_dhan_client_id_here
DHAN_ACCESS_TOKEN=your_dhan_access_token_here
```
Do NOT set `LIVE_EXECUTION_ENABLED=true` unless you are prepared for real orders to be placed.

## 6. DHAN CONNECTION

To test the Dhan connection safely in Paper Mode (or live), ensure you have filled out your `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` inside the `.env` file.

## 7. BACKEND START

Run the backend server using uvicorn:

```powershell
uvicorn backend.app.main:app --reload
```
*(Or use the specific startup script if one exists)*

## 8. FRONTEND START

The frontend is mostly static. You can serve it using a simple Python HTTP server from another terminal:

```powershell
cd frontend
python -m http.server 8000
```

## 9. HEALTH CHECK

Navigate to:
- Backend Health: `http://localhost:8000/health` or `http://127.0.0.1:8000/docs` (depending on the port uvicorn runs on)
- Frontend URL: `http://localhost:8000/` 

## 10. PAPER MODE

Paper mode is strictly enforced if `LIVE_EXECUTION_ENABLED=false`. All generated orders will be simulated against live market data, but not submitted to the broker.

## 11. TROUBLESHOOTING

- **Missing Modules**: If you get an `ImportError`, ensure you have activated your `venv` and run `pip install -r requirements.txt`.
- **Dhan Auth Errors**: Check your `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` in `.env`.
- **Port Conflicts**: If port 8000 is taken, use `python -m http.server 8080` for the frontend and update any backend CORS configuration accordingly.
