import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class TrojmiastoScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("trojmiasto", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        print(f"Scraping Trojmiasto: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        try: 
            await page.click("button[id*='gdpr-confirm']", timeout=3000)
        except: 
            try: await page.get_by_text("Przejdź do serwisu").click(timeout=1000)
            except: pass
        
        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
                
            print(f"Trojmiasto Page {current_page}")
            
            listing = await page.query_selector_all("div.ogl-item")
            if not listing:
                 listing = await page.query_selector_all("div.list__item")
            
            if not listing:
                 links = await page.query_selector_all("a[href*='/wiadomosc/']")
                 if not links: break
            
            page_offers = []
            for card in listing:
                try:
                    link_el = await card.query_selector("a")
                    link = await link_el.get_attribute("href") if link_el else ""
                    if not link: continue
                    if not link.startswith("http"):
                        link = "https://ogloszenia.trojmiasto.pl" + link
                    
                    text_content = self.safe_text(await card.inner_text())
                    
                    title_el = await card.query_selector("h2, h3")
                    title = self.safe_text(await title_el.inner_text()) if title_el else "No Title"
                    
                    price, area, price_m2, location = "", "", "", "N/A"
                    
                    pm = re.search(r'(\d[\d\s]*\s?zł)', text_content)
                    if pm: price = self.safe_text(pm.group(1))
                    
                    am = re.search(r'(\d+[.,]?\d*)\s*m2', text_content)
                    if am: area = am.group(1)
                    
                    pmm = re.search(r'(\d[\d\s]*)\s*zł/m2', text_content)
                    if pmm: price_m2 = pmm.group(1).replace(" ", "")
                    
                    if "Gdańsk" in text_content:
                         loc_match = re.search(r'(Gdańsk[^0-9\n\r]*)', text_content)
                         if loc_match: location = loc_match.group(1).split(",")[0:2]
                         if isinstance(location, list): location = ", ".join(location)
                    
                    floor = self.parse_floor(text_content)
                    garden = self.check_garden(text_content)
    
                    page_offers.append({
                        "url": link, "title": title, 
                        "price": self.normalize_price(price), "area": self.normalize_area(area), 
                        "price_per_m2": self.normalize_price(price_m2), "location": location, 
                        "source": "trojmiasto",
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
