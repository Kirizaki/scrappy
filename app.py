from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import asyncio
import json
from storage import load_offers, update_offer_status, CSV_FILE
from scraper import run_scraper

app = FastAPI()

# Mount templates
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/offers")
async def get_offers():
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
async def toggle_favorite(payload: dict):
    url = payload.get("url")
    current_status = payload.get("status") # True or False
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    
    success = update_offer_status(url, "is_favorite", current_status)
    if not success:
        raise HTTPException(status_code=404, detail="Offer not found")
    return {"status": "success", "new_state": current_status}

@app.post("/api/offers/hide")
async def toggle_hidden(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
        
    success = update_offer_status(url, "is_hidden", True)
    if not success:
        raise HTTPException(status_code=404, detail="Offer not found")
    return {"status": "success"}


# Global lock
scraper_running = False

@app.get("/api/status")
async def get_status():
    return {"running": scraper_running}

@app.post("/api/run")
async def trigger_scraper(background_tasks: BackgroundTasks):
    global scraper_running
    if scraper_running:
        raise HTTPException(status_code=409, detail="Scraper already running")
    
    scraper_running = True
    background_tasks.add_task(run_scraper_wrapper)
    return {"status": "Scraper started in background"}

@app.get("/api/config")
async def get_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

@app.post("/api/config")
async def update_config(request: Request):
    new_config = await request.json()
    with open("config.json", "w") as f:
        json.dump(new_config, f, indent=4)
    return {"status": "Config saved"}

async def run_scraper_wrapper():
    global scraper_running
    try:
        await run_scraper()
    except Exception as e:
        print(f"Scraper error: {e}")
    finally:
        scraper_running = False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
