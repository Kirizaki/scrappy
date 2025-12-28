import asyncio
import json
import re
import logging
from playwright.async_api import async_playwright
from storage import save_offers
from scrapers.olx import OlxScraper
from scrapers.otodom import OtodomScraper
from scrapers.morizon import MorizonScraper
from scrapers.trojmiasto import TrojmiastoScraper
from scrapers.nieruchomosci_online import NieruchomosciOnlineScraper
from scrapers.gratka import GratkaScraper
from scrapers.domiporta import DomiportaScraper
from scrapers.adresowo import AdresowoScraper
from scrapers.szybko import SzybkoScraper
from scrapers.gethome import GethomeScraper
from scrapers.okolica import OkolicaScraper
from scrapers.tabelaofert import TabelaofertScraper
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from logger_config import setup_logging

SCRAPERS = {
    "trojmiasto": TrojmiastoScraper,
    "otodom": OtodomScraper,
    "olx": OlxScraper,
    "morizon": MorizonScraper,
    "nieruchomosci_online": NieruchomosciOnlineScraper,
    "gratka": GratkaScraper,
    "domiporta": DomiportaScraper,
    "gratka": GratkaScraper,
    "domiporta": DomiportaScraper,
    "adresowo": AdresowoScraper,
    "szybko": SzybkoScraper,
    "gethome": GethomeScraper,
    "okolica": OkolicaScraper,
    "tabelaofert": TabelaofertScraper,
}

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"

TROJMIASTO_DISTRICT_MAP = {
    "wrzeszcz": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz górny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz/",
    "wrzeszcz dolny": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/wrzeszcz-dolny/",
    "strzyża": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/strzyza/",
    "aniołki": "https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/mieszkanie/gdansk/aniolki/"
}

NIERUCHOMOSCI_ONLINE_DISTRICT_MAP = {
    "wrzeszcz": "https://www.nieruchomosci-online.pl/szukaj.html?3,mieszkanie,sprzedaz,,Gda%C5%84sk+Wrzeszcz",
    "wrzeszcz górny": "https://www.nieruchomosci-online.pl/szukaj.html?3,mieszkanie,sprzedaz,,Gda%C5%84sk+Wrzeszcz",
    "wrzeszcz dolny": "https://www.nieruchomosci-online.pl/szukaj.html?3,mieszkanie,sprzedaz,,Gda%C5%84sk+Wrzeszcz",
    "strzyża": "https://www.nieruchomosci-online.pl/szukaj.html?3,mieszkanie,sprzedaz,,Gda%C5%84sk+Strzy%C5%BCa",
    "aniołki": "https://www.nieruchomosci-online.pl/szukaj.html?3,mieszkanie,sprzedaz,,Gda%C5%84sk+Anio%C5%82ki"
}

GRATKA_DISTRICT_MAP = {
    "wrzeszcz": "https://gratka.pl/nieruchomosci/mieszkania/gdansk/wrzeszcz",
    "wrzeszcz górny": "https://gratka.pl/nieruchomosci/mieszkania/gdansk/wrzeszcz",
    "wrzeszcz dolny": "https://gratka.pl/nieruchomosci/mieszkania/gdansk/wrzeszcz",
    "strzyża": "https://gratka.pl/nieruchomosci/mieszkania/gdansk/strzyza",
    "aniołki": "https://gratka.pl/nieruchomosci/mieszkania/gdansk/aniolki"
}

DOMIPORTA_DISTRICT_MAP = {
    "wrzeszcz": "https://www.domiporta.pl/mieszkanie/sprzedam/pomorskie/gdansk/wrzeszcz",
    "wrzeszcz górny": "https://www.domiporta.pl/mieszkanie/sprzedam/pomorskie/gdansk/wrzeszcz",
    "wrzeszcz dolny": "https://www.domiporta.pl/mieszkanie/sprzedam/pomorskie/gdansk/wrzeszcz-dolny",
    "strzyża": "https://www.domiporta.pl/mieszkanie/sprzedam/pomorskie/gdansk/strzyza",
    "aniołki": "https://www.domiporta.pl/mieszkanie/sprzedam/pomorskie/gdansk/aniolki"
}

ADRESOWO_DISTRICT_MAP = {
    # Adresowo uses slugs in URL: mieszkania/gdansk/wrzeszcz/
    "wrzeszcz": "https://adresowo.pl/mieszkania/gdansk/wrzeszcz/",
    "wrzeszcz górny": "https://adresowo.pl/mieszkania/gdansk/wrzeszcz-gorny/", # Guessing slug
    "wrzeszcz dolny": "https://adresowo.pl/mieszkania/gdansk/wrzeszcz-dolny/", # Guessing slug
    "strzyża": "https://adresowo.pl/mieszkania/gdansk/strzyza/",
    "aniołki": "https://adresowo.pl/mieszkania/gdansk/aniolki/"
}

SZYBKO_DISTRICT_MAP = {
    "wrzeszcz": "https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/Gda%C5%84sk/Wrzeszcz",
    "wrzeszcz górny": "https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/Gda%C5%84sk/Wrzeszcz",
    "wrzeszcz dolny": "https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/Gda%C5%84sk/Wrzeszcz",
    "strzyża": "https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/Gda%C5%84sk/Strzy%C5%BCa",
    "aniołki": "https://szybko.pl/l/na-sprzedaz/lokal-mieszkalny/Gda%C5%84sk/Anio%C5%82ki"
}

GETHOME_DISTRICT_MAP = {
    "wrzeszcz": "https://gethome.pl/mieszkania/na-sprzedaz/gdansk/wrzeszcz/",
    "wrzeszcz górny": "https://gethome.pl/mieszkania/na-sprzedaz/gdansk/wrzeszcz/",
    "wrzeszcz dolny": "https://gethome.pl/mieszkania/na-sprzedaz/gdansk/wrzeszcz/",
    "strzyża": "https://gethome.pl/mieszkania/na-sprzedaz/gdansk/strzyza/",
    "aniołki": "https://gethome.pl/mieszkania/na-sprzedaz/gdansk/aniolki/"
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

    elif portal == "domiporta":
        if min_area: query["Surface.From"] = min_area
        if max_price: query["Price.To"] = max_price
        # Domiporta ground floor: Floor.From=0&Floor.To=0 (or similar?)
        # Verified params: Floor.From, Floor.To. 0 is ground.
        if ground_floor: 
            query["Floor.From"] = "0"
            query["Floor.To"] = "0"
        
        # Garden not easily filterable by param usually, handled in post-filter
        
        # District handled by base url path usually
        
    elif portal == "adresowo":
        # params /f/[city]/[dist]/p[min]-[max]/a[min]-[max]
        # But base_url often already has city/dist if mapped
        
        # We need to construct the filter path segments
        # Parse base_url to check what we have
        path = parsed.path.rstrip("/")
        
        # Base might be /mieszkania/gdansk/ or /mieszkania/gdansk/wrzeszcz/
        # Filter prefix is /f/ instead of /mieszkania/ for filters?
        # Inspection showed: https://adresowo.pl/f/mieszkania/gdansk/p50-70
        # If we have district: https://adresowo.pl/f/mieszkania/gdansk/wrzeszcz/p50-70 ??
        # Let's verify with inspection results: 
        # "https://adresowo.pl/f/mieszkania/gdansk/p30-40" worked.
        
        # If we just append query params, Adresowo might ignore them.
        # It seems Adresowo uses path segments for everything.
        
        filter_parts = []
        
        # Price: p[min]-[max] (in thousands?? No, inspection said p50-70 for 500k-700k implies 10k unit?)
        # User entered 500000, 700000. 
        # Inspection script: value = 500000 -> url p50-70. 
        # So 50 corresponds to 500,000. Unit is 10,000.
        if max_price:
             val = int(float(max_price) / 10000)
             filter_parts.append(f"p0-{val}")
             
        # Area: a[min]-[max]
        if min_area:
             val = int(float(min_area))
             filter_parts.append(f"a{val}-1000") # Cap at big number
             
        # If filters exist, we might need to change /mieszkania/ to /f/mieszkania/ ?
        # Or just append?
        # Let's try appending to path if base is clean.
        # But wait, if base is /mieszkania/gdansk/, and we want /f/mieszkania/gdansk/...
        
        if filter_parts:
            # Reconstruct path safely
            # Check if starts with /mieszkania/
            if path.startswith("/mieszkania/"):
                new_path = "/f" + path
            elif path.startswith("/f/mieszkania/"):
                new_path = path
            else:
                new_path = path # Should not happen given config
                
            for part in filter_parts:
                new_path += "/" + part
                
            parsed = parsed._replace(path=new_path)
            # Re-parse query to empty to avoid duplicates if any
            query = {}

    elif portal == "szybko":
        if min_area: query["meters_min"] = min_area
        if max_price: query["price_max_sell"] = max_price
        # Using strict params found: price_min_sell, meters_min.
        # But user gave max_price. Szybko likely has price_max_sell.
        # Subagent saw: price_max_sell, meters_max.
        
    elif portal in ["nieruchomosci_online", "gratka"]:
        return base_url
        
    elif portal == "okolica":
        if district:
            query["district"] = district
            
    elif portal == "tabelaofert":
        if min_area: query["metraz_od"] = min_area
        if max_price: query["cena_do"] = max_price
        # Tabelaofert uses specific city/district paths, but search params also work
        # Base URLs in config usually include city, e.g. /sprzedaz/mieszkania/gdynia
        if district: query["lokalizacja"] = district
        
    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

async def run_scraper(progress_callback=None):
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
        "trojmiasto": TrojmiastoScraper(config),
        "nieruchomosci_online": NieruchomosciOnlineScraper(config),
        "gratka": GratkaScraper(config),
        "domiporta": DomiportaScraper(config),
        "domiporta": DomiportaScraper(config),
        "adresowo": AdresowoScraper(config),
        "szybko": SzybkoScraper(config),
        "gethome": GethomeScraper(config),
        "okolica": OkolicaScraper(config),
        "tabelaofert": TabelaofertScraper(config),
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
                                 elif p_name == "nieruchomosci_online":
                                     d_lower = d.lower().strip()
                                     if d_lower in NIERUCHOMOSCI_ONLINE_DISTRICT_MAP:
                                         current_base_url = NIERUCHOMOSCI_ONLINE_DISTRICT_MAP[d_lower]
                                 elif p_name == "gratka":
                                     if d_lower in GRATKA_DISTRICT_MAP:
                                         current_base_url = GRATKA_DISTRICT_MAP[d_lower]
                                 elif p_name == "domiporta":
                                     d_lower = d.lower().strip()
                                     if d_lower in DOMIPORTA_DISTRICT_MAP:
                                         current_base_url = DOMIPORTA_DISTRICT_MAP[d_lower]
                                 elif p_name == "adresowo":
                                     if d_lower in ADRESOWO_DISTRICT_MAP:
                                         current_base_url = ADRESOWO_DISTRICT_MAP[d_lower]
                                 elif p_name == "szybko":
                                     d_lower = d.lower().strip()
                                     if d_lower in SZYBKO_DISTRICT_MAP:
                                         current_base_url = SZYBKO_DISTRICT_MAP[d_lower]
                                 elif p_name == "gethome":
                                     d_lower = d.lower().strip()
                                     if d_lower in GETHOME_DISTRICT_MAP:
                                         current_base_url = GETHOME_DISTRICT_MAP[d_lower]
                                         
                                 final_url = await build_url(current_base_url, iter_filters, p_name)
                                 items_to_scrape.append((p_name, final_url, max_pages, [d]))
                         else:
                             final_url = await build_url(base_url, filters, p_name)
                             items_to_scrape.append((p_name, final_url, max_pages, []))

        all_gathered = []
        total_tasks = len(items_to_scrape)

        for i, (portal_name, url, max_pages, district_context) in enumerate(items_to_scrape):
            if portal_name not in scrapers: continue
            
            # Report Progress
            if progress_callback:
                task_desc = f"{portal_name.title()} - {district_context[0] if district_context else 'All'}"
                progress_callback(i, total_tasks, task_desc)

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                scraper = scrapers[portal_name]
                site_offers = await scraper.scrape(page, url, max_pages)
                
                logger.info(f"[{portal_name.upper()}] Found {len(site_offers)} offers.")
                
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
                    logger.info(f"[{portal_name.upper()}] Filtered {original_count} -> {len(offers_to_save)} offers.")
                
                if offers_to_save:
                    await asyncio.to_thread(save_offers, offers_to_save)
                    all_gathered.extend(offers_to_save)
                    
            except Exception as e:
                logger.error(f"Error scraping {portal_name}: {e}")
            finally:
                await page.close()
                await context.close()
        
        # Final update
        if progress_callback:
            progress_callback(total_tasks, total_tasks, "Done")

        await browser.close()
        logger.info(f"Total offers: {len(all_gathered)}")

if __name__ == "__main__":
    setup_logging()
    asyncio.run(run_scraper())
