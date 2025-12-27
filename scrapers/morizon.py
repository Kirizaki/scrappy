import asyncio
import re
from .base import BaseScraper
from playwright.async_api import Page

class MorizonScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("morizon", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        print(f"Scraping Morizon: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        try: await page.click("button#onetrust-accept-btn-handler", timeout=3000)
        except: pass
        
        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
                
            print(f"Morizon Page {current_page}")
            # Wait for dynamic content
            await asyncio.sleep(2)

            cards = await page.query_selector_all("div.list-result-row")
            if not cards: cards = await page.query_selector_all("div[data-cy='listing-item']")
            if not cards: cards = await page.query_selector_all("section div a[href*='/oferta/']") 

            # Deduplicate if we found loose links instead of cards
            if cards and await cards[0].get_attribute("href"):
                 # These are links, not cards. We need to process them differently or find their parents.
                 # For simplicity, if we found direct links, we might just be looking at the wrong thing.
                 # Let's try to find their parent container.
                 pass
            
            # Additional fallback: Morizon new layout uses specific classes often
            if not cards:
                cards = await page.query_selector_all("a[data-cy='listing-item-link-area']")
                # If these are just links, we might miss price context if it is outside.
                # Usually Morizon wraps everything in a div.
            
            if not cards:
                break

            page_offers = []
            for card in cards:
                try:
                     # Get full text of the card/container for regex extraction
                     # If card is just <a> tag, we might need to go up to parent?
                     # Check if card has 'price' text?
                     
                     # If card is an 'a' tag, try to find parent?
                     tag = await card.evaluate("el => el.tagName")
                     if tag == "A":
                         # Take parent
                         card = await card.query_selector("xpath=..")
                         # Maybe grand parent?
                         # Let's just trust inner_text of the element we found first if it has content
                     
                     text_content = self.safe_text(await card.inner_text())
                     
                     link_el = await card.query_selector("a")
                     if not link_el: 
                         # Maybe the card itself is the link?
                         if await card.evaluate("el => el.tagName") == "A":
                             link_el = card
                     
                     link = await link_el.get_attribute("href") if link_el else ""
                     if not link: continue
                     if not link.startswith("http"): link = "https://www.morizon.pl" + link
                     
                     title = "Morizon Offer"
                     h_el = await card.query_selector("h2, h3")
                     if h_el: title = self.safe_text(await h_el.inner_text())
                     
                     price, area, price_m2, location = "", "", "", "N/A"
                     
                     # Regex extraction from full text
                     pm = re.search(r'(\d[\d\s]*\s?zł)', text_content)
                     if pm: price = self.safe_text(pm.group(1))
                     
                     am = re.search(r'(\d+[.,]?\d*)\s*m²', text_content)
                     if am: area = am.group(1)
                     
                     pmm = re.search(r'(\d[\d\s]*)\s*zł/m²', text_content)
                     if pmm: price_m2 = self.safe_text(pmm.group(1))
                     
                     # Location
                     header_links = await card.query_selector_all("h2 span, h3 span") 
                     for h in header_links:
                         txt = self.safe_text(await h.inner_text())
                         if "," in txt: location = txt; break
                     
                     if location == "N/A":
                         loc_match = re.search(r'(Gdańsk[^0-9\n]*)', text_content)
                         if loc_match: location = loc_match.group(1).strip()
                     
                     floor = self.parse_floor(text_content)
                     garden = self.check_garden(text_content)
                     
                     page_offers.append({"url": link, "title": title, 
                         "price": self.normalize_price(price), "area": self.normalize_area(area), 
                         "price_per_m2": self.normalize_price(price_m2), "location": location, "source": "morizon",
                         "floor": floor, "garden": garden})
                except: pass
            
            all_offers.extend(page_offers)
            
            # Pagination
            try:
                # Look for "Next" arrow/button
                # Morizon: usually <a class="mz-pagination-number__btn--next"> or similar
                # Also check for "Następna" text
                
                next_btn = await page.query_selector("a[aria-label*='Następna']")
                if not next_btn:
                    next_btn = await page.query_selector(".mz-pagination-number__btn--next")
                
                if next_btn:
                     href = await next_btn.get_attribute("href")
                     if href:
                         # click or goto? click is safer for SPA
                         await next_btn.click()
                         await page.wait_for_load_state("domcontentloaded")
                         current_page += 1
                         await asyncio.sleep(1)
                     else: break
                else: break
            except: break
            
        return all_offers
