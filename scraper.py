import asyncio
import json
import re
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError
from storage import save_offers

CONFIG_FILE = "config.json"

def normalize_price(price_str):
    if not price_str: return None
    # Remove 'zł', spaces, replace ',' with '.'
    # Keep digits, dot, comma
    clean = re.sub(r'[^\d,.]', '', str(price_str))
    clean = clean.replace(" ", "").replace(",", ".")
    try:
        # Handle cases like "1.200" meaning 1200 or 1.2?
        # Typically "500 000" -> 500000. "500.000" -> 500000.
        # But "1,5" -> 1.5.
        # Simple heuristic: if '.' appears and it's 3 digits from end, it might be thousands separator?
        # Polish locale usually uses space for thousands and comma for decimal.
        # Let's assume input "500 000 zł" -> "500000".
        # Input "500,000 zł" (unlikely in PL, usually space) -> "500000".
        # Input "345,50 zł" -> 345.5.
        
        # Simpler: remove all spaces. Replace comma with dot.
        # If multiple dots? "1.000.000" -> "1000000".
        # If we replaced comma with dot, we might have "1.5".
        # Let's just strip everything non-numeric except last comma/dot.
        # Actually, let's keep it simple: Strip all spaces. Replace comma with dot.
        return float(clean)
    except:
        return None

def normalize_area(area_str):
    if not area_str: return None
    # "50,5 m2" -> 50.5
    clean = str(area_str).lower().replace("m2", "").replace("m²", "").replace(" ", "").replace(",", ".")
    try:
        return float(clean)
    except:
        return None

def parse_floor(text):
    if not text: return None
    text_lower = text.lower()
    if "parter" in text_lower or "poziom 0" in text_lower:
        return 0
    # "1 piętro", "3 p.", "piętro 2"
    m = re.search(r'(?:piętro|p\.|p\b)\s*(\d+)', text_lower) # piętro 1
    if m: return int(m.group(1))
    
    m2 = re.search(r'(\d+)\s*(?:piętro|p\.|p\b)', text_lower) # 1 piętro
    if m2: return int(m2.group(1))
    
    return None

def check_garden(text):
    if not text: return False
    t = text.lower()
    return any(x in t for x in ["ogród", "ogródek", "garden", "działka"])

def check_filters(offer, filters):
    # Min Area
    if filters.get("min_area"):
        val = normalize_area(offer.get("area"))
        if val is not None and val < float(filters["min_area"]):
            return False
            
    # Max Price
    if filters.get("max_price"):
        val = normalize_price(offer.get("price"))
        if val is not None and val > float(filters["max_price"]):
            return False
            
    # Ground Floor Only
    if filters.get("ground_floor"):
        f = offer.get("floor")
        # If detected and NOT 0, reject.
        # If NOT detected (None), keep (benefit of doubt) or reject?
        # User implies filters are broken. Let's be semi-strict: if we see "1 p.", reject.
        if f is not None and f != 0:
            return False
            
    # Has Garden
    if filters.get("garden"):
        # If garden NOT detected, reject?
        # Most listings with garden boast about it.
        if not offer.get("garden", False):
            # Try checking title just in case custom logic didn't catch it
            if not check_garden(offer.get("title", "")):
                return False
                
    return True

TROJMIASTO_DISTRICT_MAP = {
    "wrzeszcz": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz górny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz dolny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz-dolny/",
    "strzyża": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/strzyza/",
    "aniołki": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/aniolki/"
}

def safe_text(text: str) -> str:
    if not text:
        return ""
    # Replace newlines and tabs with space, strip whitespace
    return " ".join(text.split())

async def scrape_olx(page: Page, url: str, max_pages: int = 0):
    print(f"Scraping OLX: {url}")
    await page.goto(url, wait_until="domcontentloaded")
    
    # Cookie consent
    try:
        await page.click("button[id='onetrust-accept-btn-handler']", timeout=3000)
    except:
        pass

    all_offers = []
    current_page = 1
    
    while True:
        if max_pages > 0 and current_page > max_pages:
            break
            
        print(f"OLX Page {current_page}")
        
        try:
            await page.wait_for_selector("div[data-cy='l-card']", timeout=5000)
        except:
             break # No more items
             
        cards = await page.query_selector_all("div[data-cy='l-card']")
        page_offers = []
        
        for card in cards:
            try:
                title_el = await card.query_selector("h6")
                title = safe_text(await title_el.inner_text()) if title_el else "No Title"
                
                link_el = await card.query_selector("a")
                link = await link_el.get_attribute("href") if link_el else ""
                if link and not link.startswith("http"):
                    link = "https://www.olx.pl" + link
                
                # Title Fallback
                if title == "No Title" and link:
                    try:
                        slug = link.split('/')[-1]
                        if "-ID" in slug: slug = slug.split("-ID")[0]
                        elif "CID" in slug: slug = slug.split("-CID")[0]
                        title = slug.replace(".html", "").replace("-", " ").title()
                    except: pass
                
                price_el = await card.query_selector("p[data-testid='ad-price']")
                price = safe_text(await price_el.inner_text()) if price_el else ""
                
                text_content = await card.inner_text()
                area = "N/A"
                price_m2 = "N/A"
                
                area_match = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
                if area_match: area = area_match.group(1)
                
                pm2_match = re.search(r'(\d+\s?\d+)\s*zł/m²', text_content)
                if pm2_match: price_m2 = pm2_match.group(1).replace(" ", "")

                # Extract extras
                floor = parse_floor(text_content)
                garden = check_garden(text_content)

                page_offers.append({
                    "url": link,
                    "title": title,
                    "price": price,
                    "area": area,
                    "price_per_m2": price_m2,
                    "source": "olx",
                    "floor": floor,
                    "garden": garden
                })
            except Exception as e:
                continue
        
        all_offers.extend(page_offers)
        
        # Next Page
        try:
             # Look for simple pagination or assume query param updates?
             # OLX usually has data-cy="pagination-forward"
             next_btn = await page.query_selector("[data-cy='pagination-forward']")
             if next_btn:
                 await next_btn.click()
                 await page.wait_for_load_state("domcontentloaded")
                 current_page += 1
                 await asyncio.sleep(1) # Polite delay
             else:
                 break
        except:
             break
             
    return all_offers

async def scrape_otodom(page: Page, url: str, max_pages: int = 0):
    print(f"Scraping Otodom: {url}")
    await page.goto(url, wait_until="domcontentloaded")
    
    try:
        await page.click("button#onetrust-accept-btn-handler", timeout=3000)
    except:
        pass
        
    all_offers = []
    current_page = 1
    
    while True:
        if max_pages > 0 and current_page > max_pages:
            break
            
        print(f"Otodom Page {current_page}")
    
        try:
            await page.wait_for_selector("article", timeout=10000)
        except:
             # Often happens if no results or blocked
             break

        results = await page.query_selector_all("article")
        page_offers = []
        
        for card in results:
            try:
                link_el = await card.query_selector("a")
                link = await link_el.get_attribute("href") if link_el else ""
                if link and not link.startswith("http"):
                    link = "https://www.otodom.pl" + link
                    
                # Title: Try headers or alt text
                title_el = await card.query_selector("h3")
                if not title_el: title_el = await card.query_selector("h2")
                if not title_el: title_el = await card.query_selector("h4")
                if not title_el: title_el = await card.query_selector("[data-cy='listing-item-title']")
                
                title = safe_text(await title_el.inner_text()) if title_el else ""
                
                if not title:
                     img_el = await card.query_selector("img")
                     if img_el: title = safe_text(await img_el.get_attribute("alt"))
                
                # Title Fallback
                if not title and link:
                    try:
                        slug = link.split('/')[-1]
                        if "-ID" in slug: slug = slug.split("-ID")[0]
                        elif "CID" in slug: slug = slug.split("-CID")[0]
                        title = slug.replace(".html", "").replace("-", " ").title()
                    except: pass
                
                if not title: title = "No Title"
                
                # Extract text content for everything else
                text_content = safe_text(await card.inner_text())
                
                price = ""
                area = "N/A"
                price_m2 = "N/A"
                location = "N/A"
                
                # Price regex: look for "zł" 
                # Avoid picking up price/m2 (which has /m²)
                # Usually standard price: "500 000 zł" at end or beginning
                # We find all matches of X zł (not followed by /)
                prices = re.findall(r'(\d[\d\s]*\s?zł)(?!\/)', text_content)
                if prices:
                    # Usually the main price is the first or largest? 
                    # Often price per m2 comes after.
                    # Let's take the first one that looks like a total price (longer number?)
                    # Simplified: First match is usually valid.
                    price = prices[0]
                
                area_match = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
                if area_match: area = area_match.group(1)

                pm2_match = re.search(r'(\d+\s?\d+)\s*zł/m²', text_content)
                if pm2_match: price_m2 = pm2_match.group(1).replace(" ", "")
                
                # Location strategy: Look for "Gdańsk" or similar in text
                # We can iterate over common cities in config or just greedy grab
                # "Gdańsk, Wrzeszcz" pattern 
                # Let's look for known city names in the text
                known_cities = ["Gdańsk", "Gdynia", "Sopot", "Rumia", "Reda", "Wejherowo"]
                found_loc = None
                for city in known_cities:
                    if city in text_content:
                        # Try to extract the context?
                        # Regex: (City, [Word]+)
                        loc_m = re.search(fr'({city}[^0-9\n\r]*)', text_content)
                        if loc_m:
                            found_loc = loc_m.group(1).strip().strip(",-")
                            break
                
                if found_loc:
                     location = found_loc
                else:
                     # Fallback: look for generic "City, District" pattern if possible, 
                     # but hard without DOM structure.
                     pass
                     
                floor = parse_floor(text_content)
                garden = check_garden(text_content)

                page_offers.append({
                    "url": link,
                    "title": title,
                    "price": price,
                    "area": area,
                    "price_per_m2": price_m2,
                    "location": location,
                    "source": "otodom",
                    "floor": floor,
                    "garden": garden
                })
            except Exception as e:
                pass
        
        all_offers.extend(page_offers)
        
        try:
            # Pagination: look for next button by aria label or generic "next" icon logic
            # Otodom typically: <button aria-label="następna strona">
            next_btn = await page.query_selector("button[aria-label*='następna']") 
            if not next_btn:
                 # Check generic pagination next (li:last-child often)
                 next_btn = await page.query_selector("nav[role='navigation'] button:last-child") 

            if next_btn and await next_btn.is_enabled():
                await next_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                current_page += 1
                await asyncio.sleep(1)
            else:
                break
        except:
            break
            
    return all_offers

async def scrape_morizon(page: Page, url: str, max_pages: int = 0):
    # Morizon pagination is tricky, often loads via button "More" or standard numbers.
    # For now, implemented as single page due to complexity, but struct is here.
    # ...
    return await _generic_scrape_morizon(page, url)

async def _generic_scrape_morizon(page: Page, url: str):
    # ... existing morizon logic ...
    # We will reuse existing logic but just wrapped for cleaner code if needed
    # For this patch, I'll keep it simple and just do 1 page for others or simple loop if easy
    # Morizon has changed often.
    
    # Let's just paste the original body for Morizon/Trojmiasto but respect max_pages=0 (loop?)
    # Trojmiasto has simple pagination usually.
    return await scrape_morizon_impl(page, url)

async def scrape_morizon_impl(page: Page, url: str): 
    print(f"Scraping Morizon: {url}")
    await page.goto(url, wait_until="domcontentloaded")
    try: await page.click("button#onetrust-accept-btn-handler", timeout=3000)
    except: pass
    
    offers = []
    # Morizon robust strategy: Find all article or generic listing items
    # Typically <div class="list-result-row"> or <a class="cascading-display-box">
    # Try multiple selectors
    cards = await page.query_selector_all("div.list-result-row")
    if not cards: cards = await page.query_selector_all("div[data-cy='listing-item']")
    if not cards: cards = await page.query_selector_all("section") # sometimes just sections
    
    # Fallback: Find all links with /oferta/
    if not cards:
         links = await page.query_selector_all("a[href*='/oferta/']")
         # Deduplicate parents?
         # Proceed with link-based extraction if standard cards fail
         for link_el in links:
             # Look for parent container?
             # Simplified: just extract from link text if possible or traverse up?
             # For now, let's stick to known selectors but log if empty
             pass

    for card in cards:
        try:
             text_content = safe_text(await card.inner_text())
             link_el = await card.query_selector("a")
             link = await link_el.get_attribute("href") if link_el else ""
             if not link: continue
             if not link.startswith("http"): link = "https://www.morizon.pl" + link
             
             title = "Morizon Offer"
             h_el = await card.query_selector("h2, h3")
             if h_el: title = safe_text(await h_el.inner_text())
             
             price, area, price_m2, location = "", "", "", "N/A"
             
             # Regex extraction from full text
             pm = re.search(r'(\d[\d\s]*\s?zł)', text_content)
             if pm: price = safe_text(pm.group(1))
             
             am = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
             if am: area = am.group(1)
             
             pmm = re.search(r'(\d[\d\s]*)\s*zł/m²', text_content)
             if pmm: price_m2 = safe_text(pmm.group(1))
             
             # Location
             header_links = await card.query_selector_all("h2 span, h3 span") 
             for h in header_links:
                 txt = safe_text(await h.inner_text())
                 if "," in txt: location = txt; break
             
             if location == "N/A":
                 loc_match = re.search(r'(Gdańsk[^0-9\n]*)', text_content)
                 if loc_match: location = loc_match.group(1).strip()
             
             floor = parse_floor(text_content)
             garden = check_garden(text_content)
             
             offers.append({"url": link, "title": title, "price": price, "area": area, 
                 "price_per_m2": price_m2, "location": location, "source": "morizon",
                 "floor": floor, "garden": garden})
        except: pass
    return offers

async def scrape_trojmiasto(page: Page, url: str, max_pages: int = 0):
    print(f"Scraping Trojmiasto: {url}")
    await page.goto(url, wait_until="domcontentloaded")
    try: await page.click("button[id*='gdpr-confirm']", timeout=3000)
    except: 
        try: await page.get_by_text("Przejdź do serwisu").click(timeout=1000)
        except: pass
    
    all_offers = []
    current_page = 1
    
    while True:
        if max_pages > 0 and current_page > max_pages:
            break
            
        print(f"Trojmiasto Page {current_page}")
        
        # Trojmiasto robust strategy:
        # Selector 'div.ogl-item' was working but maybe changed?
        # Try finding all wrapping divs that contain price and title class?
        # Re-verify selectors: usually .ogl-item or .list__item
        
        listing = await page.query_selector_all("div.ogl-item")
        if not listing:
             listing = await page.query_selector_all("div.list__item") # updated potential class
        
        # Super fallback: Find links to offers and use their containers?
        if not listing:
            # Look for <a> with class 'ogl-item__link' or 'list__item__link'
             links = await page.query_selector_all("a[href*='/wiadomosc/']")
             # This might be just links, not cards.
             # Let's hope one of the container classes works.
        
        page_offers = []
        for card in listing:
            try:
                link_el = await card.query_selector("a")
                link = await link_el.get_attribute("href") if link_el else ""
                if not link: continue
                # Trojmiasto links often relative
                if not link.startswith("http"):
                    link = "https://ogloszenia.trojmiasto.pl" + link
                
                text_content = safe_text(await card.inner_text())
                
                title_el = await card.query_selector("h2, h3")
                title = safe_text(await title_el.inner_text()) if title_el else "No Title"
                
                # Regex extraction for safety
                price, area, price_m2, location = "", "", "", "N/A"
                
                pm = re.search(r'(\d[\d\s]*\s?zł)', text_content)
                if pm: price = safe_text(pm.group(1))
                
                # Area: X m2
                am = re.search(r'(\d+[.,]?\d*)\s*m2', text_content)
                if am: area = am.group(1)
                
                pmm = re.search(r'(\d[\d\s]*)\s*zł/m2', text_content)
                if pmm: price_m2 = pmm.group(1).replace(" ", "")
                
                # Location from details or text
                # "Gdańsk, Morena, 3 pokoje..."
                if "Gdańsk" in text_content:
                     loc_match = re.search(r'(Gdańsk[^0-9\n\r]*)', text_content)
                     if loc_match: location = loc_match.group(1).split(",")[0:2] # Take first 2 parts?
                     if isinstance(location, list): location = ", ".join(location)
                
                floor = parse_floor(text_content)
                garden = check_garden(text_content)

                page_offers.append({
                    "url": link, "title": title, "price": price, "area": area, 
                    "price_per_m2": price_m2, "location": location, "source": "trojmiasto",
                    "floor": floor, "garden": garden
                })
            except: pass
            
        all_offers.extend(page_offers)
        
        try:
            next_el = await page.query_selector("a.pages__controls__next")
            if next_el:
                href = await next_el.get_attribute("href")
                if href and "javascript" not in href:
                     await next_el.click()
                     await page.wait_for_load_state("domcontentloaded")
                     current_page += 1
                     await asyncio.sleep(1)
                else: break
            else: break
        except: break

    return all_offers


async def build_url(base_url, filters, portal):
    # Ensure base_url has no existing query params that conflict, or just append safely
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    
    min_area = filters.get("min_area")
    max_price = filters.get("max_price")
    ground_floor = filters.get("ground_floor")
    garden = filters.get("garden")
    district = filters.get("district")
    
    if portal == "olx":
        if min_area: query["search[filter_float_m:from]"] = min_area
        if max_price: query["search[filter_float_price:to]"] = max_price
        if ground_floor: query["search[filter_enum_floor_select][0]"] = "floor_0"
        # Force secondary market
        query["search[filter_enum_market][0]"] = "secondary"
        if district: query["q"] = district # Text search
        
    elif portal == "otodom":
        if min_area: query["areaMin"] = min_area
        if max_price: query["priceMax"] = max_price
        if ground_floor: 
            query["floorMin"] = "0"
            query["floorMax"] = "0"
        if garden: query["features"] = ['["GARDEN"]'] 
        # Force secondary market
        query["market"] = "SECONDARY"
        if district: query["q"] = district
        
    elif portal == "morizon":
        if min_area: query["ps[living_area_min]"] = min_area
        if max_price: query["ps[price_max]"] = max_price
        if ground_floor: query["ps[floor][0]"] = "1"
        if garden: query["ps[has_garden]"] = "1"
        # Force secondary market (2 usually means secondary)
        query["ps[market_type][0]"] = "2"
        
    elif portal == "trojmiasto":
        current_ri = query.get("ri", ["_"])[0]
        c_min, c_max = (current_ri.split("_", 1) if "_" in current_ri else ("", ""))
        new_min_area = min_area if min_area else c_min
        if new_min_area or c_max: query["ri"] = f"{new_min_area}_{c_max}"
             
        current_rm = query.get("rm", ["_"])[0]
        p_min, p_max = (current_rm.split("_", 1) if "_" in current_rm else ("", ""))
        new_max_price = max_price if max_price else p_max
        if p_min or new_max_price: query["rm"] = f"{p_min}_{new_max_price}"
             
        if garden: query["kl"] = "2300"
        if ground_floor: query["pi"] = "0_0"
        # Force secondary market
        query["rynek"] = "W"
        if district: query["slowa"] = district

    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

async def run_scraper():
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        
    all_offers = []
    
    # Check for new config structure
    filters = config.get("filters", {})
    portals_config = config.get("portals", config)
    
    # Helper for district filtering
    # Helper for district filtering
    raw_district = filters.get("district", "")
    if isinstance(raw_district, list):
        districts = [d.strip() for d in raw_district if d and isinstance(d, str)]
    else:
        districts = [d.strip() for d in raw_district.split(';')] if raw_district else []
    districts = [d for d in districts if d] # clean empty
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        
        items_to_scrape = []
        
        # Structure normalization
        if "filters" in config:
             for p_name, p_conf in portals_config.items():
                 if p_conf.get("enabled", True):
                     base_url = p_conf.get("base_url")
                     max_pages = p_conf.get("max_pages", 0)
                     
                     if base_url:
                         # If districts defined, create a URL for EACH district
                         if districts:
                             for d in districts:
                                 # Create specific filter for this iteration
                                 iter_filters = filters.copy()
                                 iter_filters["district"] = d
                                 
                                 # Trójmiasto Specific District URL override
                                 current_base_url = base_url
                                 if p_name == "trojmiasto":
                                     d_lower = d.lower().strip()
                                     if d_lower in TROJMIASTO_DISTRICT_MAP:
                                         current_base_url = TROJMIASTO_DISTRICT_MAP[d_lower]
                                         
                                 final_url = await build_url(current_base_url, iter_filters, p_name)
                                 # We store the district context to allow strict filtering PER district fetch
                                 items_to_scrape.append((p_name, final_url, max_pages, [d]))
                         else:
                             # No district, just run once
                             final_url = await build_url(base_url, filters, p_name)
                             items_to_scrape.append((p_name, final_url, max_pages, []))
        else:
             for p_name, items in portals_config.items():
                 for item in items:
                     items_to_scrape.append((p_name, item["url"], 0, []))

        for portal, url, max_pages, district_context in items_to_scrape:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                site_offers = []
                if portal == "olx":
                    site_offers = await scrape_olx(page, url, max_pages)
                elif portal == "otodom":
                    site_offers = await scrape_otodom(page, url, max_pages)
                elif portal == "morizon":
                    # Morizon generic wrapper
                    site_offers = await scrape_morizon_impl(page, url) 
                elif portal == "trojmiasto":
                    site_offers = await scrape_trojmiasto(page, url, max_pages)
                
                print(f"Found {len(site_offers)} offers on {portal} (URL: {url})")
                
                # INCREMENTAL PROCESSING & SAVING
                # Filter strictly if needed
                offers_to_save = []
                
                # Combined filtering
                original_count = len(site_offers)
                for offer in site_offers:
                    # 1. District Check (Existing)
                    if district_context:
                        offer_loc_str = (str(offer.get("location", "")) + " " + str(offer.get("title", ""))).lower()
                        match = False
                        for d in district_context:
                            if d.lower() in offer_loc_str:
                                match = True
                                break
                        if not match:
                            continue # Skip this offer

                    # 2. Config Filters Check (New)
                    if not check_filters(offer, filters):
                        continue # Skip this offer
                        
                    offers_to_save.append(offer)
                
                if len(offers_to_save) < original_count:
                    print(f"Filtered {original_count} -> {len(offers_to_save)} offers based on config metrics & district.")

                # Async save immediately
                if offers_to_save:
                    await asyncio.to_thread(save_offers, offers_to_save)
                    
                all_offers.extend(offers_to_save)
                
            except Exception as e:
                print(f"Failed to scrape {portal} - {url}: {e}")
            finally:
                await page.close()
                await context.close()
                    
        await browser.close()
    
    # Final log, but saving is done incrementally
    print(f"Total offers gathered and processed: {len(all_offers)}")

if __name__ == "__main__":
    asyncio.run(run_scraper())
