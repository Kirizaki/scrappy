import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class OtodomScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("otodom", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
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
            # Dynamic content, wait a bit
            await asyncio.sleep(2) 
        
            try:
                await page.wait_for_selector("article", timeout=10000)
            except:
                 break
    
            results = await page.query_selector_all("article")
            print(f"Found {len(results)} articles on Otodom Page {current_page}")
            page_offers = []
            
            for card in results:
                try:
                    link_el = await card.query_selector("a")
                    link = await link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = "https://www.otodom.pl" + link
                        
                    # Title
                    title_el = await card.query_selector("h3")
                    if not title_el: title_el = await card.query_selector("h2")
                    if not title_el: title_el = await card.query_selector("h4")
                    if not title_el: title_el = await card.query_selector("[data-cy='listing-item-title']")
                    
                    title = self.safe_text(await title_el.inner_text()) if title_el else ""
                    
                    if not title:
                         img_el = await card.query_selector("img")
                         if img_el: title = self.safe_text(await img_el.get_attribute("alt"))
                    
                    if not title and link:
                        try:
                            slug = link.split('/')[-1]
                            if "-ID" in slug: slug = slug.split("-ID")[0]
                            elif "CID" in slug: slug = slug.split("-CID")[0]
                            title = slug.replace(".html", "").replace("-", " ").title()
                        except: pass
                    
                    if not title: title = "No Title"
                    
                    text_content = self.safe_text(await card.inner_text())
                    
                    # Price
                    price_el = await card.query_selector("[data-cy='listing-item-price']")
                    price = self.safe_text(await price_el.inner_text()) if price_el else ""
                    
                    # Area
                    area_el = await card.query_selector("[data-cy='listing-item-area']")
                    area = self.safe_text(await area_el.inner_text()) if area_el else ""
    
                    if not price or not area:
                        prices = re.findall(r'(\d{1,3}(?:[\s\xa0]\d{3})*\s?zł)(?!\/)', text_content)
                        if prices and not price:
                            price = prices[0]
                        if not area:
                            area_match = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
                            if area_match: area = area_match.group(1)
                    
                    # Price/m2
                    pm2_match = re.search(r'(\d+[\s\xa0]?\d+)\s*zł/m²', text_content)
                    price_m2 = pm2_match.group(1).replace(" ", "").replace("\xa0", "") if pm2_match else ""
    
                    # Location
                    loc_el = await card.query_selector("[data-cy='listing-item-location']")
                    location = self.safe_text(await loc_el.inner_text()) if loc_el else "N/A"
                    
                    if location == "N/A":
                        known_cities = ["Gdańsk", "Gdynia", "Sopot", "Rumia", "Reda", "Wejherowo"]
                        found_loc = None
                        for city in known_cities:
                            if city in text_content:
                                loc_m = re.search(fr'({city}[^0-9\n\r]*)', text_content)
                                if loc_m:
                                    found_loc = loc_m.group(1).strip().strip(",-")
                                    break
                        if found_loc: location = found_loc
                    
                    # Floor
                    floor_el = await card.query_selector("[data-cy='listing-item-floor']")
                    if floor_el:
                        floor = self.parse_floor(self.safe_text(await floor_el.inner_text()))
                    else:
                        floor = self.parse_floor(text_content)
                    
                    garden = self.check_garden(text_content)
    
                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price),
                        "area": self.normalize_area(area),
                        "price_per_m2": self.normalize_price(price_m2),
                        "location": location,
                        "source": "otodom",
                        "floor": floor,
                        "garden": garden
                    })
                except Exception as e:
                    pass
            
            all_offers.extend(page_offers)
            
            try:
                # Pagination
                next_btn = await page.query_selector("button[aria-label*='następna']") 
                if not next_btn:
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
