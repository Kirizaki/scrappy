from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import asyncio
import json
import logging
import numpy as np
import base64
from storage import load_offers, update_offer_status, CSV_FILE
from scraper import run_scraper
from ignore_this import check_password
from logger_config import setup_logging
from analize import run_analysis_and_update

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
    df = df.replace([np.inf, -np.inf, np.nan], None)
    
    # Decode Base64 summaries for the frontend display
    if "analysis_summary" in df.columns:
        def safe_decode(val):
            if val and isinstance(val, str) and not val.startswith("<div"):
                try:
                    return base64.b64decode(val).decode('utf-8')
                except:
                    return val
            return val
        df["analysis_summary"] = df["analysis_summary"].apply(safe_decode)
         
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

@app.post("/api/offers/analyze")
async def start_analysis(request: Request, background_tasks: BackgroundTasks):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = await request.json()
    url = payload.get("url")
    additional_urls = payload.get("additional_urls", [])
    
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    
    # We don't check if it's already running here, analize.py will handle status updates.
    background_tasks.add_task(run_analysis_and_update, url, additional_urls)
    return {"status": "Analysis started"}

@app.get("/api/offers/analysis")
async def get_analysis(url: str):
    df = load_offers()
    if url in df["url"].values:
        # Handle NaNs for JSON
        df = df.replace([np.inf, -np.inf, np.nan], None)
        
        row = df[df["url"] == url].iloc[0]
        status = row.get("analysis_status", "none")
        summary = row.get("analysis_summary", None)
        
        # Decode Base64 if it's done
        if status == "done" and summary:
            try:
                summary = base64.b64decode(summary).decode('utf-8')
            except Exception as e:
                logger.error(f"Failed to decode analysis summary for {url}: {e}")
                # Keep original if it's already plain HTML (for migration transition)
        
        return {
            "status": status,
            "summary": summary
        }
    raise HTTPException(status_code=404, detail="Offer not found")

@app.post("/api/offers/analysis/reset")
async def reset_analysis(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = await request.json()
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    
    update_offer_status(url, "analysis_status", "none")
    update_offer_status(url, "analysis_summary", None)
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
