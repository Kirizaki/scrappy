import asyncio
import pandas as pd
import sys
import os
import re
from playwright.async_api import async_playwright

# --- Helper Functions ---

def normalize_year(text):
    if not text: return None
    # Look for 4 digits in range 1000-2030
    matches = re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', text)
    if matches:
        return int(matches[0])
    return None

async def extract_year_otodom(page):
    try:
        # Otodom generic fallback - try to find "Rok budowy"
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content)
        if m:
            return int(m.group(1))
            
        return None
    except:
        return None

async def extract_year_olx(page):
    try:
        content = await page.content()
        m = re.search(r'Rok budowy[:\s]*(\d{4})', content, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None
    except:
        return None

async def extract_year_trojmiasto(page):
    try:
        # Investigated selector: .xogField--rok_budowy .xogField__value
        el = await page.query_selector(".xogField--rok_budowy .xogField__value")
        if el:
            txt = await el.text_content()
            matches = re.findall(r'\d{4}', txt)
            if matches: return int(matches[0])
            
        # Fallback to text search if specific field missing
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None
    except:
        return None
        
async def extract_year_morizon(page):
    try:
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None
    except:
        return None

async def get_year_built(page, url):
    try:
        print(f"Checking: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        
        # Cookie consent might be needed
        try:
            await page.click("button[id*='accept-btn']", timeout=1000)
        except: pass

        if "otodom" in url:
            y = await extract_year_otodom(page)
        elif "olx" in url:
            y = await extract_year_olx(page)
        elif "trojmiasto" in url:
            y = await extract_year_trojmiasto(page)
        elif "morizon" in url:
            y = await extract_year_morizon(page)
        else:
            # Generic fallback
            content = await page.content()
            m = re.search(r'(?:Rok budowy|Building Year).*?(\d{4})', content, re.IGNORECASE)
            y = int(m.group(1)) if m else None
            
        return y
    except Exception as e:
        print(f"Error checking {url}: {e}")
        return None

async def process_offers(input_file):
    if not os.path.exists(input_file):
        print(f"File {input_file} not found")
        return

    df = pd.read_csv(input_file)
    print(f"Loaded {len(df)} offers.")
    
    # Ensure is_hidden column exists
    if "is_hidden" not in df.columns:
        df["is_hidden"] = False
    
    updated_offers = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
             user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for index, row in df.iterrows():
            url = str(row['url'])
            
            # Check year
            year = await get_year_built(page, url)
            
            # Logic: 
            # - If year < 1960: KEEP (is_hidden = False)
            # - If year not found: KEEP (is_hidden = False)
            # - If year >= 1960: HIDE (is_hidden = True)
            
            status = ""
            row_dict = row.to_dict()
            
            if year is None:
                # Keep active
                row_dict["is_hidden"] = False
                status = "YEAR NOT FOUND (KEEP)"
            elif year < 1960:
                row_dict["is_hidden"] = False
                status = f"YEAR {year} < 1960 (KEEP)"
            else:
                row_dict["is_hidden"] = True
                status = f"YEAR {year} >= 1960 (HIDE)"
            
            row_dict['scraped_year'] = year if year else ""
            
            updated_offers.append(row_dict)
            print(f"[{index+1}/{len(df)}] {status} - {str(row.get('title', 'No Title'))[:30]}...")
            
        await browser.close()
        
    # Save
    new_df = pd.DataFrame(updated_offers)
    output_file = f"processed_{os.path.basename(input_file)}"
    
    # Ensure columns order if possible, keeping original columns plus is_hidden update
    new_df.to_csv(output_file, index=False)
    print(f"\nDone! Saved {len(new_df)} offers to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python filter_by_year.py <input_csv_file>")
    else:
        asyncio.run(process_offers(sys.argv[1]))
