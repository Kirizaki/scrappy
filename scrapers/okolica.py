import asyncio
from .base import BaseScraper
from playwright.async_api import Page

class OkolicaScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("okolica", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        self.logger.info(f"Scraping Okolica: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Cookie Consent first to avoid blocking inputs
        try:
            consent_btn = await page.wait_for_selector(".t-acceptAllButton", timeout=3000)
            if consent_btn:
                await consent_btn.click()
                await asyncio.sleep(1)
        except:
            pass
        
        # Parse district from URL if present
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(url)
        params = parse_qs(parsed_url.query)
        district = params.get("district", [None])[0]
        
        if district:
            # Force a clean search page without any pre-existing query tags or states
            self.logger.info(f"Navigating to clean search page for district: {district}")
            await page.goto("https://www.okolica.pl/search/", wait_until="networkidle")
            
            # Wait a bit for any background scripts
            await asyncio.sleep(2)
            
            try:
                # Find the location input
                query_input = await page.wait_for_selector("#browser_query", state="visible", timeout=10000)
                if query_input:
                    self.logger.info(f"Typing district: {district}")
                    await query_input.click()
                    await query_input.fill("") 
                    await asyncio.sleep(1)
                    # Type slowly to trigger autocomplete
                    for char in district:
                        await page.keyboard.type(char)
                        await asyncio.sleep(0.3)
                    
                    # Wait 500ms as requested
                    await asyncio.sleep(0.5)
                    
                    # Wait for autocomplete
                    suggestion_selector = "ul.ui-autocomplete li.ui-menu-item"
                    try:
                        await page.wait_for_selector(suggestion_selector, state="visible", timeout=12000)
                        
                        # Find the suggestion that best matches
                        suggestions = page.locator(suggestion_selector)
                        count = await suggestions.count()
                        suggestion_texts = []
                        for i in range(count):
                            txt = await suggestions.nth(i).inner_text()
                            suggestion_texts.append(txt)
                        
                        self.logger.info(f"Suggestions found: {suggestion_texts}")
                        
                        target_index = -1
                        # We want a suggestion that contains the district and ideally the city "Gdańsk"
                        for i, text in enumerate(suggestion_texts):
                            t_lower = text.lower()
                            d_lower = district.lower()
                            if d_lower in t_lower:
                                if "gdańsk" in t_lower:
                                    target_index = i
                                    break
                                if target_index == -1:
                                    target_index = i
                        
                        if target_index != -1:
                            target_text = suggestion_texts[target_index]
                            self.logger.info(f"Selecting suggestion: {target_text}")
                            await suggestions.nth(target_index).click()
                        else:
                            self.logger.warning(f"District {district} not found in suggestions. Pressing Enter as fallback.")
                            await page.keyboard.press("Enter")
                            
                        # Wait for results refresh - search triggers on click or Enter
                        self.logger.info("Waiting for results to update...")
                        await asyncio.sleep(5)
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception as e:
                        self.logger.warning(f"Autocomplete did not appear: {e}. Pressing Enter as fallback.")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(5)
            except Exception as e:
                self.logger.warning(f"Error selecting district: {e}")

        all_offers = []
        current_page = 1
        
        while True:
            if max_pages > 0 and current_page > max_pages:
                break
            
            self.logger.info(f"Okolica Page {current_page}")
            
            # Wait for offers list
            try:
                await page.wait_for_selector(".property", timeout=10000)
            except:
                self.logger.info("No listing items found - timed out.")
                break

            cards = await page.query_selector_all(".property")
            
            if not cards:
                 self.logger.info("No cards found.")
                 break
            
            self.logger.info(f"Found {len(cards)} offers on Okolica Page {current_page}")
            page_offers = []
            
            for card in cards:
                try:
                    # Link & Title
                    title_el = await card.query_selector(".property-title a")
                    if not title_el: continue
                    
                    title = await title_el.inner_text()
                    link = await title_el.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = f"https://www.okolica.pl{link}"
                        
                    # Price
                    price_el = await card.query_selector(".price")
                    price_text = await price_el.inner_text() if price_el else ""
                    
                    # Area
                    # Area is usually in the 3rd list item of property-data
                    area_text = ""
                    data_items = await card.query_selector_all(".property-data li span")
                    for item in data_items:
                        txt = await item.inner_text()
                        if "m2" in txt or "m²" in txt:
                            area_text = txt
                            break
                    # Fallback if loop didn't find it (sometimes it's just a number)
                    if not area_text and len(data_items) >= 3:
                         area_text = await data_items[2].inner_text()

                    # Location
                    loc_el = await card.query_selector(".property-address")
                    location = await loc_el.inner_text() if loc_el else "N/A"
                    
                    page_offers.append({
                        "url": link,
                        "title": title,
                        "price": self.normalize_price(price_text),
                        "area": self.normalize_area(area_text),
                        "price_per_m2": 0.0,
                        "location": location,
                        "source": "okolica"
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Error parsing Okolica card: {e}")
            
            all_offers.extend(page_offers)
            
            # Pagination
            # Next button: a[title="Następna strona"]
            if max_pages > 0 and current_page >= max_pages:
                break
                
            try:
                next_btn = await page.query_selector('a[title="Następna strona"]')
                if next_btn:
                     href = await next_btn.get_attribute("href")
                     if href:
                         await next_btn.click()
                         await page.wait_for_load_state("domcontentloaded")
                         current_page += 1
                         await asyncio.sleep(2)
                     else:
                         break
                else:
                    self.logger.info("No next button found.")
                    break
            except Exception as e:
                self.logger.info(f"Pagination done/error: {e}")
                break
                
        return all_offers
