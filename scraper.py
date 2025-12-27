import asyncio
import json
import re
from playwright.async_api import async_playwright
from storage import save_offers
from scrapers.olx import OlxScraper
from scrapers.otodom import OtodomScraper
from scrapers.morizon import MorizonScraper
from scrapers.trojmiasto import TrojmiastoScraper
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

CONFIG_FILE = "config.json"

TROJMIASTO_DISTRICT_MAP = {
    "wrzeszcz": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz górny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz dolny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz-dolny/",
    "strzyża": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/strzyza/",
    "aniołki": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/aniolki/"
}

# Shared check_filters logic (could be moved to base but useful here for post-filtering)
def check_filters(offer, filters):
    # Min Area
    if filters.get("min_area"):
        val = offer.get("area")
        if val is not None and val < float(filters["min_area"]):
            return False
            
    # Max Price
    if filters.get("max_price"):
        val = offer.get("price")
        if val is not None and val > float(filters["max_price"]):
            return False
            
    # Ground Floor Only
    if filters.get("ground_floor"):
        f = offer.get("floor")
        if f is None or f != 0:
            return False
            
    # Has Garden
    if filters.get("garden"):
        if not offer.get("garden", False):
            # Try checking title just in case
            t = offer.get("title", "").lower()
            if not any(x in t for x in ["ogród", "ogródek", "garden", "działka", "ogrod"]):
                return False
                
    return True

async def build_url(base_url, filters, portal):
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
        query["search[filter_enum_market][0]"] = "secondary"
        if district: query["q"] = district
        
    elif portal == "otodom":
        if min_area: query["areaMin"] = min_area
        if max_price: query["priceMax"] = max_price
        if ground_floor: 
            query["floorMin"] = "0"
            query["floorMax"] = "0"
        if garden: query["features"] = ['["GARDEN"]'] 
        query["market"] = "SECONDARY"
        if district: query["q"] = district
        
    elif portal == "morizon":
        if min_area: query["ps[living_area_min]"] = min_area
        if max_price: query["ps[price_max]"] = max_price
        if ground_floor: query["ps[floor][0]"] = "1"
        if garden: query["ps[has_garden]"] = "1"
        query["ps[market_type][0]"] = "2"
        
        if district:
            # Morizon structure: /mieszkania/{city}/{district}/
            # We assume base_url ends with city, e.g. .../gdansk/
            # We need to slugify the district
            import unicodedata
            d_slug = unicodedata.normalize('NFKD', district).encode('ascii', 'ignore').decode('utf-8')
            d_slug = re.sub(r'[-\s]+', '-', d_slug.lower()).strip('-')
            
            # Check if likely already there
            if d_slug not in parsed.path:
                 new_path = parsed.path.rstrip("/") + "/" + d_slug + "/"
                 parsed = parsed._replace(path=new_path)
        
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
        query["rynek"] = "W"
        if district: query["slowa"] = district

    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

async def run_scraper():
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        
    filters = config.get("filters", {})
    portals_config = config.get("portals", config)
    
    # Helper for district filtering
    raw_district = filters.get("district", "")
    if isinstance(raw_district, list):
        districts = [d.strip() for d in raw_district if d and isinstance(d, str)]
    else:
        districts = [d.strip() for d in raw_district.split(';')] if raw_district else []
    districts = [d for d in districts if d] 
    
    scrapers = {
        "olx": OlxScraper(config),
        "otodom": OtodomScraper(config),
        "morizon": MorizonScraper(config),
        "trojmiasto": TrojmiastoScraper(config)
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        
        items_to_scrape = []
        if "filters" in config:
             for p_name, p_conf in portals_config.items():
                 if p_conf.get("enabled", True):
                     base_url = p_conf.get("base_url")
                     max_pages = p_conf.get("max_pages", 0)
                     
                     if base_url:
                         if districts:
                             for d in districts:
                                 iter_filters = filters.copy()
                                 iter_filters["district"] = d
                                 
                                 current_base_url = base_url
                                 if p_name == "trojmiasto":
                                     d_lower = d.lower().strip()
                                     if d_lower in TROJMIASTO_DISTRICT_MAP:
                                         current_base_url = TROJMIASTO_DISTRICT_MAP[d_lower]
                                         
                                 final_url = await build_url(current_base_url, iter_filters, p_name)
                                 items_to_scrape.append((p_name, final_url, max_pages, [d]))
                         else:
                             final_url = await build_url(base_url, filters, p_name)
                             items_to_scrape.append((p_name, final_url, max_pages, []))

        all_gathered = []

        for portal_name, url, max_pages, district_context in items_to_scrape:
            if portal_name not in scrapers: continue
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                scraper = scrapers[portal_name]
                site_offers = await scraper.scrape(page, url, max_pages)
                
                print(f"[{portal_name.upper()}] Found {len(site_offers)} offers.")
                
                offers_to_save = []
                original_count = len(site_offers)
                for offer in site_offers:
                    # 1. District Check
                    if district_context:
                        offer_loc_str = (str(offer.get("location", "")) + " " + str(offer.get("title", ""))).lower()
                        match = False
                        for d in district_context:
                            if d.lower() in offer_loc_str:
                                match = True
                                break
                        if not match:
                            continue

                    # 2. Config Filters Check
                    if not check_filters(offer, filters):
                        continue
                        
                    offers_to_save.append(offer)
                
                if len(offers_to_save) < original_count:
                    print(f"[{portal_name.upper()}] Filtered {original_count} -> {len(offers_to_save)} offers.")
                
                if offers_to_save:
                    await asyncio.to_thread(save_offers, offers_to_save)
                    all_gathered.extend(offers_to_save)
                    
            except Exception as e:
                print(f"Error scraping {portal_name}: {e}")
            finally:
                await page.close()
                await context.close()
                
        await browser.close()
        print(f"Total offers: {len(all_gathered)}")

if __name__ == "__main__":
    asyncio.run(run_scraper())
