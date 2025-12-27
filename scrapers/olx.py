import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class OlxScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("olx", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
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
                    title = self.safe_text(await title_el.inner_text()) if title_el else "No Title"
                    
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
                    price = self.safe_text(await price_el.inner_text()) if price_el else ""
                    
                    text_content = await card.inner_text()
                    area = "N/A"
                    price_m2 = "N/A"
                    
                    area_match = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
                    if area_match: area = area_match.group(1)
                    
                    pm2_match = re.search(r'(\d+\s?\d+)\s*zł/m²', text_content)
                    if pm2_match: price_m2 = pm2_match.group(1).replace(" ", "")

                    # Location
                    location = "N/A"
                    loc_el = await card.query_selector("p[data-testid='location-date']")
                    if loc_el:
                        location = self.safe_text(await loc_el.inner_text())
                        if " - " in location:
                            location = location.split(" - ")[0]
                    
                    floor = self.parse_floor(text_content)
                    garden = self.check_garden(text_content)

                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price),
                        "area": self.normalize_area(area),
                        "price_per_m2": self.normalize_price(price_m2),
                        "location": location,
                        "source": "olx",
                        "floor": floor,
                        "garden": garden
                    })
                except Exception as e:
                    continue
            
            all_offers.extend(page_offers)
            
            # Next Page
            try:
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
