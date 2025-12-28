from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import asyncio
import json
import logging
from storage import load_offers, update_offer_status, CSV_FILE
from scraper import run_scraper
from ignore_this import check_password
from logger_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI()

AUTH_COOKIE = "scrappy_auth"

# Mount templates
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

def is_authenticated(request: Request):
    return request.cookies.get(AUTH_COOKIE) == "true"

@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def post_login(payload: dict):
    password = payload.get("password", "").lower()
    if check_password(password):
        response = JSONResponse(content={"status": "success"})
        response.set_cookie(key=AUTH_COOKIE, value="true", max_age=31536000) # 1 year
        return response
    raise HTTPException(status_code=401, detail="Invalid password")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/offers")
async def get_offers(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    df = load_offers()
    # Filter out hidden
    # Actually user said "mark as hidden... will keep in csv, but will not be shown in the table"
    # So we filter here.
    if "is_hidden" in df.columns:
        df = df[df["is_hidden"] != True]
    
    # Sort by scraped_at desc
    if "scraped_at" in df.columns:
         df = df.sort_values(by="scraped_at", ascending=False)
    
    # Handle NaNs and Infs for JSON
    import numpy as np
    df = df.replace([np.inf, -np.inf, np.nan], None)
         
    return df.to_dict(orient="records")

@app.post("/api/offers/favorite")
async def toggle_favorite(request: Request, payload: dict):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    url = payload.get("url")
    current_status = payload.get("status") # True or False
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    
    success = update_offer_status(url, "is_favorite", current_status)
    if not success:
        raise HTTPException(status_code=404, detail="Offer not found")
    return {"status": "success", "new_state": current_status}

@app.post("/api/offers/hide")
async def toggle_hidden(request: Request, payload: dict):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
        
    success = update_offer_status(url, "is_hidden", True)
    if not success:
        raise HTTPException(status_code=404, detail="Offer not found")
    return {"status": "success"}



# Global Lock & Progress
import time
scraper_running = False
scraper_start_time = 0
scraper_progress = {
    "processed": 0,
    "total": 0,
    "current_task": "",
    "status": "idle", # idle, running, done
    "eta_seconds": None
}

def update_progress(processed, total, task_name):
    global scraper_progress, scraper_start_time
    scraper_progress["processed"] = processed
    scraper_progress["total"] = total
    scraper_progress["current_task"] = task_name
    scraper_progress["status"] = "running"
    
    if processed > 0 and total > 0:
        elapsed = time.time() - scraper_start_time
        avg_time = elapsed / processed
        remaining = total - processed
        scraper_progress["eta_seconds"] = int(avg_time * remaining)
    else:
        scraper_progress["eta_seconds"] = None

    if processed >= total and total > 0:
         scraper_progress["status"] = "done"
         scraper_progress["eta_seconds"] = 0

@app.get("/api/status")
async def get_status(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"running": scraper_running}

@app.get("/api/progress")
async def get_progress(request: Request):
    if not is_authenticated(request):
         raise HTTPException(status_code=401, detail="Unauthorized")
    return scraper_progress

@app.post("/api/run")
async def trigger_scraper(request: Request, background_tasks: BackgroundTasks):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    global scraper_running, scraper_progress, scraper_start_time
    if scraper_running:
        raise HTTPException(status_code=409, detail="Scraper already running")
    
    scraper_running = True
    scraper_start_time = time.time()
    # Reset progress
    scraper_progress = {
        "processed": 0,
        "total": 0, 
        "current_task": "Starting...",
        "status": "running",
        "eta_seconds": None
    }
    
    background_tasks.add_task(run_scraper_wrapper)
    return {"status": "Scraper started in background"}

@app.get("/api/config")
async def get_config(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

@app.post("/api/config")
async def update_config(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    new_config = await request.json()
    with open("config.json", "w") as f:
        json.dump(new_config, f, indent=4)
    return {"status": "Config saved"}

async def run_scraper_wrapper():
    global scraper_running
    try:
        await run_scraper(progress_callback=update_progress)
    except Exception as e:
        logger.error(f"Scraper error: {e}")
    finally:
        scraper_running = False
        scraper_progress["status"] = "idle"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
