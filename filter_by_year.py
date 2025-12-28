import asyncio
import pandas as pd
import sys
import os
import re
import json
import logging
from playwright.async_api import async_playwright
from logger_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

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
        # Otodom often has it in a specific section
        for selector in ["div[data-cy='ad.top-information.table']", "section[data-cy='ad.parameters.table']"]:
            el = await page.query_selector(selector)
            if el:
                txt = await el.inner_text()
                m = re.search(r'Rok budowy.*?(\d{4})', txt, re.IGNORECASE | re.DOTALL)
                if m: return int(m.group(1))
        
        # Fallback to full text
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None

async def extract_year_olx(page):
    try:
        # OLX parameters table
        el = await page.query_selector("table[data-testid='table-param-list']")
        if el:
            txt = await el.inner_text()
            m = re.search(r'Rok budowy[:\s]*(\d{4})', txt, re.IGNORECASE)
            if m: return int(m.group(1))
        
        content = await page.content()
        m = re.search(r'Rok budowy[:\s]*(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None

async def extract_year_trojmiasto(page):
    try:
        # Trojmiasto has specific classes
        el = await page.query_selector(".xogField--rok_budowy .xogField__value")
        if el:
            txt = await el.text_content()
            m = re.search(r'\d{4}', txt)
            if m: return int(m.group(0))
            
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None
        
async def extract_year_morizon(page):
    try:
        # Morizon specs
        el = await page.query_selector("section.mz-section-parameters")
        if el:
            txt = await el.inner_text()
            m = re.search(r'Rok budowy[:\s]*(\d{4})', txt, re.IGNORECASE)
            if m: return int(m.group(1))
            
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None

async def extract_year_nieruchomosci_online(page):
    try:
        # Nieruchomosci-online params
        el = await page.query_selector(".params-list")
        if el:
            txt = await el.inner_text()
            m = re.search(r'Rok budowy.*?(\d{4})', txt, re.IGNORECASE)
            if m: return int(m.group(1))
            
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None

async def extract_year_gratka(page):
    try:
        # Gratka parameters
        el = await page.query_selector(".parameters__container")
        if el:
            txt = await el.inner_text()
            m = re.search(r'Rok budowy[:\s]*(\d{4})', txt, re.IGNORECASE)
            if m: return int(m.group(1))
            
        content = await page.content()
        m = re.search(r'Rok budowy.*?(\d{4})', content, re.IGNORECASE)
        return int(m.group(1)) if m else None
    except: return None

async def extract_year_tabelaofert(page):
    try:
        # Tabelaofert often has it in details or investment info
        content = await page.content()
        # Look for words like "oddania", "ukończenia", "rok", "budowy"
        m = re.search(r'(?:Rok budowy|Termin oddania|Data ukończenia).*?(\d{4})', content, re.IGNORECASE)
        if m: return int(m.group(1))
        
        # Just look for any 4-digit number that looks like a year in specific sections
        el = await page.query_selector('div[class*="Szczegoly-module"]')
        if el:
             txt = await el.inner_text()
             m = re.search(r'\b(19\d{2}|20[0-2]\d)\b', txt)
             if m: return int(m.group(1))
             
        return None
    except: return None

async def get_year_built(page, url):
    try:
        logger.info(f"Checking: {url}")
        
        # Use a more aggressive timeout for slow sites, but allow for early exit
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            logger.warning(f"Timeout or error loading {url}: {e}")
            # Try to continue if we have some content
        
        # Cookie consent handling - try a few common patterns
        try:
            for selector in ["button#onetrust-accept-btn-handler", "button[id*='accept']", "button:has-text('OK')", "button:has-text('Zgadzam')"]:
                if await page.query_selector(selector):
                    await page.click(selector, timeout=2000)
                    break
        except: pass

        if "otodom.pl" in url:
            y = await extract_year_otodom(page)
        elif "olx.pl" in url:
            y = await extract_year_olx(page)
        elif "trojmiasto.pl" in url:
            y = await extract_year_trojmiasto(page)
        elif "morizon.pl" in url:
            y = await extract_year_morizon(page)
        elif "nieruchomosci-online.pl" in url:
            y = await extract_year_nieruchomosci_online(page)
        elif "gratka.pl" in url:
            y = await extract_year_gratka(page)
        elif "tabelaofert.pl" in url:
            y = await extract_year_tabelaofert(page)
        else:
            # Generic fallback for domiporta, adresowo, szybko, gethome, okolica
            content = await page.content()
            # Try specific keyword first
            m = re.search(r'(?:Rok budowy|Building Year|Wiek budynku|Oddanie).*?(\d{4})', content, re.IGNORECASE)
            if not m:
                # Look for year in a technical parameters section if it exists
                # Many sites use <ul> or <table> for this
                params = await page.query_selector_all("ul, table, div[class*='param'], div[class*='spec']")
                for p in params:
                    txt = await p.inner_text()
                    if len(txt) < 1000: # Don't search huge blocks
                        m2 = re.search(r'\b(19\d{2}|20[0-2]\d)\b', txt)
                        if m2: 
                            y_temp = int(m2.group(1))
                            if 1800 < y_temp < 2030:
                                return y_temp
            
            y = int(m.group(1)) if m else None
            
        return y
    except Exception as e:
        logger.error(f"Error checking {url}: {e}")
        return None

async def process_offers(input_file):
    if not os.path.exists(input_file):
        logger.error(f"File {input_file} not found")
        return

    df = pd.read_csv(input_file)
    logger.info(f"Loaded {len(df)} offers.")

    max_year = 1960
    logger.info(f"Using max_year: {max_year}")
    
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
            row_dict = row.to_dict()

            # Check if likely already hidden
            is_already_hidden = False
            val = row.get("is_hidden")
            if val is True or str(val).lower() == "true":
                is_already_hidden = True

            if is_already_hidden:
                logger.info(f"[{index+1}/{len(df)}] ALREADY HIDDEN (SKIP) - {str(row.get('title', 'No Title'))[:30]}...")
                row_dict["is_hidden"] = True
                updated_offers.append(row_dict)
                continue
            
            # Check year
            year = await get_year_built(page, url)
            
            # Logic: 
            # - If year < max_year: KEEP (is_hidden = False)
            # - If year not found: KEEP (is_hidden = False)
            # - If year >= max_year: HIDE (is_hidden = True)
            
            status = ""
            
            if year is None:
                # Keep active
                row_dict["is_hidden"] = False
                status = "YEAR NOT FOUND (KEEP)"
            elif year < max_year:
                row_dict["is_hidden"] = False
                status = f"YEAR {year} < {max_year} (KEEP)"
            else:
                row_dict["is_hidden"] = True
                status = f"YEAR {year} >= {max_year} (HIDE)"
            
            # row_dict['scraped_year'] = year if year else ""
            
            updated_offers.append(row_dict)
            logger.info(f"[{index+1}/{len(df)}] {status} - {str(row.get('title', 'No Title'))[:30]}...")
            
            # Periodic save
            if (index + 1) % 10 == 0:
                temp_df = pd.DataFrame(updated_offers)
                output_file = f"processed_{os.path.basename(input_file)}"
                temp_df.to_csv(output_file, index=False)
                logger.info(f"Saved progress to {output_file}")
            
        await browser.close()
        
    # Final Save
    new_df = pd.DataFrame(updated_offers)
    output_file = f"processed_{os.path.basename(input_file)}"
    new_df.to_csv(output_file, index=False)
    logger.info(f"\nDone! Saved {len(new_df)} offers to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python filter_by_year.py <input_csv_file>")
    else:
        asyncio.run(process_offers(sys.argv[1]))
