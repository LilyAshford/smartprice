import asyncio
import aiohttp
import hashlib
import random
import json
import logging
import os
import re
import base64
from dotenv import load_dotenv
from flask import current_app
from urllib.parse import urlparse, parse_qs
import redis.asyncio as redis
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.async_api import async_playwright
from typing import Dict, Tuple, Optional, Union
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async

import config

load_dotenv()

RAINFOREST_API_KEY = os.getenv("RAINFOREST_API_KEY")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")
SCRAPEOPS_KEY = os.getenv("SCRAPEOPS_KEY")
USER_AGENTS = [
        # Chrome (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        # Chrome (macOS)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        # Chrome (Linux)
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

        # Firefox (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Windows NT 10.0; rv:125.0) Gecko/20100101 Firefox/125.0",
        # Firefox (macOS)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.5; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
        # Firefox (Linux)
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",

        # Safari (macOS)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
        # Safari (iPhone/iPad)
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPad; CPU OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",

        # Edge (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        # Edge (macOS)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",

        # Opera (Windows)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/89.0.4447.83",
        # Opera (macOS)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/89.0.4447.83",
    ]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("parser")

redis_client = None

async def init_redis():
    global redis_client
    redis_client = await get_redis_connection()

async def get_redis_connection():
    host = current_app.config.get('REDIS_HOST', 'localhost')
    port = current_app.config.get('REDIS_PORT', 6379)
    password = current_app.config.get('REDIS_PASSWORD', None)
    db_num = current_app.config.get('REDIS_DB', 0)

    url = f"redis://:{password}@{host}:{port}/{db_num}" if password else f"redis://{host}:{port}/{db_num}"
    return redis.from_url(url)


async def get_cached(key):
    try:
        r = await get_redis_connection()
        async with r.client() as conn:
            return await conn.get(key)
    except Exception as e:
        logging.error(f"Redis cache GET failed: {e}")
        return None


async def set_cached(key, value, error=False):
    try:
        r = await get_redis_connection()
        if not r: return
        ttl = 300 if error else 3600
        await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as e:
        logging.error(f"Redis cache SET failed: {e}")

async def fetch_html_scraperapi(session, url, retries=2):
    for attempt in range(retries):
        try:
            params = {'api_key': SCRAPERAPI_KEY, 'url': url, 'render': 'true', 'premium': 'true'}
            async with session.get("http://api.scraperapi.com", params=params, timeout=45) as resp:
                if resp.status != 200:
                    logger.warning(f"ScraperAPI bad status: {resp.status}")
                    continue
                return await resp.text(), resp.status
        except Exception as e:
            logger.warning(f"ScraperAPI fetch error: {e}")
            if attempt + 1 == retries:
                return {"error": "scraperapi_fetch_error", "details": str(e)}, 500

async def evade_bot_detection(context):
    page = await context.new_page()
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        window.chrome = {
            runtime: {},
            loadTimes: () => {},
            csi: () => {},
        };

        Object.defineProperty(navigator, 'languages', {
            get: () => ['ru-RU', 'ru']
        });

        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
    """)
    return page

class BaseParser:
    def __init__(self, url):
        self.url = url


async def get_ebay_oauth_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET")

    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers=headers,
            data=data
        ) as resp:
            body = await resp.json()
            if resp.status != 200:
                print("FAILED", resp.status, body)
                raise Exception(f"eBay token request failed: {body}")
            return body["access_token"]

class AmazonParser(BaseParser):
    async def parse(self, session):
        try:
            params = {
                "api_key": RAINFOREST_API_KEY,
                "type": "product",
                "url": self.url
            }
            async with session.get("https://api.rainforestapi.com/request", params=params, timeout=15) as resp:
                data = await resp.json()
                if resp.status != 200 or "product" not in data:
                    return {"error": "api_error", "status": resp.status, "details": data}, True
                product = data["product"]
                return {
                    "name": product.get("title"),
                    "price": product.get("buybox_winner", {}).get("price", {}).get("raw")
                }, False
        except Exception as e:
            return {"error": "amazon_parse_error", "details": str(e)}, True


class EbayParser(BaseParser):
    async def parse(self, session: aiohttp.ClientSession):
        api_result, has_error = await self._parse_with_api(session)

        if not has_error:
            logger.info(f"Successfully parsed via API for URL: {self.url}")
            return api_result, False

        logger.warning(
            f"API parsing failed for {self.url}. Error: {api_result.get('details', 'Unknown API error')}. "
            f"Falling back to Playwright scraping."
        )

        return await self._parse_with_playwright()

    async def _parse_with_api(self, session: aiohttp.ClientSession):
        try:
            match = re.search(r"/itm/(\d+)", self.url)
            if not match:
                return {"error": "ebay_item_id_not_found", "details": "Could not extract item ID from URL"}, True
            item_id = match.group(1)

            try:
                token = await get_ebay_oauth_token()
                if not token:
                    return {"error": "ebay_auth_failed"}, True
            except Exception as e:
                return {"error": "ebay_auth_exception", "details": str(e)}, True

            domain = urlparse(self.url).netloc.lower().replace('www.', '')
            marketplace_map = {'ebay.com': 'EBAY_US', 'ebay.co.uk': 'EBAY_GB', 'ebay.de': 'EBAY_DE',
                               'ebay.ca': 'EBAY_CA',
                               'ebay.com.au': 'EBAY_AU'}
            marketplace_id = marketplace_map.get(domain, 'EBAY_US')

            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            }

            api_url_legacy = "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id"
            params_legacy = {"legacy_item_id": item_id}
            logger.info(f"Attempting to fetch item {item_id} as a standard item.")

            async with session.get(api_url_legacy, headers=headers, params=params_legacy) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(f"Successfully fetched item {item_id} as a standard item.")
                    data = json.loads(response_text)
                    return {"name": data.get("title"), "price": float(data.get("price", {}).get("value"))}, False

                if resp.status == 400 and "get_items_by_item_group" in response_text:
                    logger.warning(f"Item {item_id} is an item group. Switching to group API.")
                    api_url_group = "https://api.ebay.com/buy/browse/v1/item/get_items_by_item_group"
                    params_group = {"item_group_id": item_id}

                    async with session.get(api_url_group, headers=headers, params=params_group) as group_resp:
                        group_response_text = await group_resp.text()
                        if group_resp.status == 200:
                            logger.info(f"Successfully fetched item group {item_id}.")
                            group_data = json.loads(group_response_text)
                            if group_data.get("items"):
                                first_item = group_data["items"][0]
                                return {"name": first_item.get("title"),
                                        "price": float(first_item.get("price", {}).get("value"))}, False
                            else:
                                return {"error": "ebay_group_empty", "details": "Item group is empty"}, True
                        else:
                            return {"error": "ebay_group_api_error", "status": group_resp.status,
                                    "details": group_response_text}, True

                logger.error(f"Ebay API error for item {item_id}: {resp.status} - {response_text}")
                return {"error": "ebay_api_error", "status": resp.status, "details": response_text}, True

        except Exception as e:
            logger.error(f"Unhandled exception in API parser: {e}", exc_info=True)
            return {"error": "ebay_api_exception", "details": str(e)}, True

    async def _parse_with_playwright(self):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=random.choice(USER_AGENTS))
                await stealth_async(page)
                await page.goto(self.url, timeout=60000, wait_until="domcontentloaded")

                name_selectors = ["h1.x-item-title__mainTitle", ".x-item-title-text > .ux-textspans", "h1#itemTitle"]
                name = ""
                for selector in name_selectors:
                    elements = await page.locator(selector).all()
                    if elements:
                        name_text = await elements[0].text_content()
                        if name_text and name_text.strip():
                            name = name_text.strip()
                            break

                price_selectors = ["div.x-price-primary span.ux-textspans", "span[itemprop='price']", ".display-price"]
                price = None
                for selector in price_selectors:
                    elements = await page.locator(selector).all()
                    for element in elements:
                        price_text = await element.text_content()
                        if price_text:
                            cleaned_price = re.sub(r'[^\d.,]', '', price_text).replace(',', '.')
                            if cleaned_price:
                                try:
                                    price = float(cleaned_price)
                                    break
                                except ValueError:
                                    continue
                    if price is not None:
                        break

                await browser.close()
                if name and price is not None:
                    return {"name": name, "price": price}, False

                details = f"Could not extract name ({'found' if name else 'not found'}) or price ({'found' if price is not None else 'not found'})"
                return {"error": "ebay_scrape_failure", "details": details}, True

        except Exception as e:
            logger.error(f"eBay Playwright scraping failed: {str(e)}", exc_info=True)
            return {"error": "ebay_scrape_exception", "details": str(e)}, True

class WildberriesParser(BaseParser):
    async def parse(self, session: aiohttp.ClientSession):
        try:
            product_id = re.search(r"(?:catalog|product)/(\d+)", self.url).group(1)
            if not product_id:
                return {"error": "wildberries_invalid_url"}, True

            api_url = (
                f"https://card.wb.ru/cards/v2/detail?"
                f"appType=1&curr=rub&dest=-1257786&nm={product_id}&spp=30"
            )

            async with session.get(api_url, timeout=15) as resp:
                if resp.status != 200:
                    return {"error": f"wildberries_api_error_{resp.status}"}, True

                data = await resp.json()
                if not data.get("data", {}).get("products"):
                    return {"error": "wildberries_product_not_found"}, True

                product = data["data"]["products"][0]

                price_info = None
                if "sizes" in product and len(product["sizes"]) > 0:
                    size = product["sizes"][0]
                    if "price" in size:
                        price_info = size["price"]

                if not price_info:
                    return {"error": "wildberries_price_not_found"}, True

                price = (price_info.get("total") or price_info.get("product")) / 100

                return {
                    "name": product.get("name", "Name not specified"),
                    "price": price,
                }, False

        except aiohttp.ClientError as e:
            return {"error": "wildberries_network_error", "details": str(e)}, True
        except Exception as e:
            return {"error": "wildberries_parse_error", "details": str(e)}, True


class WalmartParser(BaseParser):
    async def parse(self, session):
        html, status = await fetch_html_scraperapi(session, self.url)
        if isinstance(html, dict): return html, True
        soup = BeautifulSoup(html, "html.parser")
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag: return {"error": "walmart_parse_error"}, True
        try:
            data = json.loads(script_tag.string)
            product_data = data['props']['pageProps']['initialData']['data']['product']
            name = product_data.get('name')
            price = product_data.get('priceInfo', {}).get('currentPrice', {}).get('price')
            return {"name": name, "price": float(price)}, False
        except Exception as e:
            return {"error": "walmart_parse_error", "details": str(e)}, True


class MockParser:
    """
    Fake parser for testing.
    Reacts to URLs starting with mock://
    Example: mock://price-drop/1 -> price dropped
    mock://target-reached/1 -> price reached target
    mock://no-change/1 -> price did not change
    """

    def __init__(self, url):
        self.url = url
        self.scenario = urlparse(url).netloc  # price-drop, target-reached, etc.
        self.product_id = urlparse(url).path.strip('/')

    async def parse(self):
        logging.info(f"Using MockParser for URL: {self.url}")

        old_price = 100.0
        target_price = 60.0

        if self.scenario == "price-drop":
            new_price = 80.0
        elif self.scenario == "target-reached":
            new_price = 50.0
        elif self.scenario == "price-increase":
            new_price = 120.0
        else:  # no-change
            new_price = 100.0

        result = {
            'name': f"Mock Product '{self.scenario}' ({self.product_id})",
            'price': new_price
        }
        return result, False



DOMAIN_PARSERS = {
    "amazon.com": AmazonParser,
    "wildberries.ru": WildberriesParser,
    "walmart.com": WalmartParser,
    "ebay.com": EbayParser
}

def get_parser(url):
    domain = urlparse(url).netloc.lower().replace('www.', '')
    return DOMAIN_PARSERS.get(domain)

async def parse_url_with_session(url: str):
    """Helper function that creates a session and calls the main parser."""
    async with aiohttp.ClientSession() as session:
        return await parse_url(url, session)


def extract_product_name(url: str) -> str | None:
    """Extracts only the product name using the basic parser."""
    data = extract_product_data(url)
    return data.get('name') if not data.get('error') and data.get('name') else None


def extract_product_price(url: str) -> float | None:
    """Extracts only the price of the product."""
    data = extract_product_data(url)
    return data.get('price') if not data.get('error') and data.get('price') is not None else None


async def parse_url(url: str, session: aiohttp.ClientSession) -> dict:
    """
    Parses a URL and returns a standardized dictionary.
    Success: {'success': True, 'name': '...', 'price': ...}
    Error:   {'success': False, 'error': '...', 'details': '...'}
    """
    parsed_uri = urlparse(url)
    if parsed_uri.scheme == 'mock':
        parser_instance = MockParser(url)
        data, has_error = await parser_instance.parse()
        return {**data, 'success': not has_error}

    domain = parsed_uri.netloc.lower().replace('www.', '')
    parser_class = DOMAIN_PARSERS.get(domain)

    if not parser_class:
        return {'success': False, 'error': f'No parser found for domain: {domain}'}

    try:
        parser_instance = parser_class(url)
        data, has_error = await parser_instance.parse(session)

        if has_error:
            return {**data, 'success': False}
        else:
            return {**data, 'success': True}
    except Exception as e:
        logger.exception(f"Unhandled exception in parser {parser_class.__name__}")
        return {'success': False, 'error': f'Parser {parser_class.__name__} failed unexpectedly', 'details': str(e)}


def extract_product_data(url: str) -> dict:
    """The main synchronous entrypoint for parsing. Always returns a dictionary."""
    try:
        if os.name == 'nt' and not asyncio.get_event_loop().is_running():
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        return run_async_in_sync(parse_url_with_session(url))
    except Exception as e:
        logger.error(f"Failed to run async parser for {url}: {e}", exc_info=True)
        return {'success': False, 'error': 'Failed to execute async parser task', 'details': str(e)}

def run_async_in_sync(coro):
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        pass
    return asyncio.run(coro)



if __name__ == "__main__":
    test_urls = [
        #"https://www.wildberries.ru/catalog/6583985/detail.aspx",
        "https://www.ebay.com/itm/256966053660?_trkparms=amclksrc%3DITM%26aid%3D1110018%26algo%3DHOMESPLICE.COMPLISTINGS%26ao%3D1%26asc%3D290501%2C290149%26meid%3D24d7519045dd4a49b234c0c13e48021a%26pid%3D101196%26rk%3D1%26rkt%3D12%26sd%3D127281867013%26itm%3D256966053660%26pmt%3D1%26noa%3D0%26pg%3D2332490%26algv%3DCompVIDesktopATF2V6ReplaceKnnV4WithVectorDbNsOptHotPlRecallCpcRecalls%26brand%3DNVIDIA&_trksid=p2332490.c101196.m2219&itmprp=cksum%3A25696605366024d7519045dd4a49b234c0c13e48021a%7Cenc%3AAQAKAAABMGd6yosUmY78X3sBQZlOPAfbcYMN1eLzdk%252BXueF57J0tezKI5wedZ2En3T%252FWoyn53ibvN%252Bdh17CwHRc8pDF4DOUBbvuDeZOvDDGGVfT9ZdusoN513hCl%252Bt1ZwXGS5YV73hYXWdmeMTqufWNC5JFAsI%252FMNyIULhUQs5qJtPO2WvnwH9dibUR9vFBatRArdCnnn0JXmPc5RLsiVoR7VRxf3kgkYW3yBuF526umSpIC2%252FUgP66x38LsSK2JVHAqlEZ4eKJ7hSCAUkjJv3zaTb%252Fy19mRWHe7dASzdeltSyed8%252FBBrO4KhrJ6r4woR0Wb8xejF7opt9Nz0QPHmc2nYgJS6ja3i%252FCbVhxUiuj9P13TkDRD8KQ769d93X3N8gAA8G%252FtzIZ6Oq62Xz39Fy7%252BIdSAbE8%253D%7Campid%3APL_CLK%7Cclp%3A2332490&itmmeta=01K20C62QJEVF8YH6RHHH3C57M",
        "https://www.ebay.com/itm/226154271181",
        "https://www.ebay.com/itm/267336611145?_skw=M3GAN&itmmeta=01K20QFE35YT8GHPJNYGPKMKM7&hash=item3e3e80f549:g:ua0AAeSwovVoflcU&itmprp=enc%3AAQAKAAAA4FkggFvd1GGDu0w3yXCmi1fH8DPwut%2FnBOKUuWT6shcRIEDEXKWNIuZwxpYqd5NPWvtbUmbQn581%2F0spjajAzqRlcTkeduTQtUJOD8%2BaUmJek7nKECISwFK8OCr7414q5jtZLUfPHmJEG5KIiYJmCfu9s%2B8V2eBXQEsnPVe9bBtip2AYxRWFiRChXNuLVOhA2wTJtCZJIyif6Dwk49INulWk2KiU5zO4%2BSO75dWKxUceix5lQOuppJOeLr99s8iRlv13j9BXm9g86ALG5jgG4d%2FkazqRD1ImOuCLkbASos5Y%7Ctkp%3ABFBM0OK9l5Bm",
        #"https://www.walmart.com/ip/Lvelia-Robot-Toy-Kids-Intelligent-Electronic-Walking-Dancing-Robot-Toys-Flashing-Lights-Music-Age-3-12-Year-Old-Boys-Girls-Birthday-Gift-Present-Oran/943196113?classType=VARIANT&athbdg=L1800&from=/search",
    ]

    async def main():
        for url in test_urls:
            print("\n---", url)
            result = await parse_url_with_session(url)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(main())

