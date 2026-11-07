import json
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.poolmanager import PoolManager
from urllib3.util.connection import create_connection

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15


def _normalize_store_url(store_url):
    return store_url.rstrip("/")


def _public_store_addresses(store_url):
    try:
        parsed = urlsplit(store_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            return None

        hostname = parsed.hostname.rstrip(".")
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            resolved = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            addresses = list({ipaddress.ip_address(result[4][0]) for result in resolved})

        if not addresses or not all(address.is_global for address in addresses):
            return None
        addresses.sort(key=lambda address: address.version)
        return hostname, [str(address) for address in addresses]
    except (OSError, ValueError):
        return None


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, *args, pinned_ip, **kwargs):
        self.pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        return create_connection(
            (self.pinned_ip, self.port),
            self.timeout,
            source_address=self.source_address,
            socket_options=self.socket_options,
        )


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection

    def __init__(self, *args, pinned_ip, **kwargs):
        super().__init__(*args, pinned_ip=pinned_ip, **kwargs)


class _PinnedHTTPSAdapter(HTTPAdapter):
    def __init__(self, pinned_ip):
        self.pinned_ip = pinned_ip
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["pinned_ip"] = self.pinned_ip
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )
        self.poolmanager.pool_classes_by_scheme["https"] = _PinnedHTTPSConnectionPool


def _safe_get(url, **kwargs):
    resolved = _public_store_addresses(url)
    if not resolved:
        raise requests.exceptions.InvalidURL("Store URL must resolve only to public HTTPS addresses.")

    _, addresses = resolved
    last_error = None
    response = None
    for address in addresses:
        with requests.Session() as session:
            session.trust_env = False
            session.mount("https://", _PinnedHTTPSAdapter(address))
            try:
                response = session.get(url, allow_redirects=False, **kwargs)
                break
            except requests.exceptions.ConnectionError as error:
                last_error = error
    if response is None:
        raise last_error or requests.exceptions.ConnectionError("Could not connect to public store address.")
    if 300 <= response.status_code < 400:
        raise requests.exceptions.TooManyRedirects("Store redirected the request.")
    return response


def test_connection(store_url, consumer_key, consumer_secret):
    """
    Confirms the store URL + credentials work by requesting a single product.
    Uses WooCommerce REST API v3 with HTTP Basic Auth (Consumer Key as
    username, Consumer Secret as password), per the official docs at
    https://woocommerce.github.io/woocommerce-rest-api-docs/
    """
    url = f"{_normalize_store_url(store_url)}/wp-json/wc/v3/products"
    try:
        response = _safe_get(
            url,
            auth=(consumer_key, consumer_secret),
            params={"per_page": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            return True, "Connection successful."
        if response.status_code == 401:
            return False, "Invalid Consumer Key or Consumer Secret."
        if response.status_code == 404:
            return False, "WooCommerce REST API was not found at this store URL. Confirm the URL and that WooCommerce is active."
        return False, f"Store responded with an unexpected status ({response.status_code})."
    except requests.exceptions.SSLError:
        return False, "Could not establish a secure connection. Confirm the store has a valid HTTPS certificate."
    except requests.exceptions.Timeout:
        return False, "The store did not respond in time. Please try again."
    except requests.exceptions.RequestException as error:
        logger.warning("WooCommerce connection test failed: %s", error)
        return False, "Unable to reach the store. Check the Store URL and try again."


def _fetch_variations(store_url, consumer_key, consumer_secret, product_id):
    url = f"{_normalize_store_url(store_url)}/wp-json/wc/v3/products/{product_id}/variations"
    try:
        response = _safe_get(
            url,
            auth=(consumer_key, consumer_secret),
            params={"per_page": 20},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_variations = response.json()
    except requests.exceptions.RequestException:
        return []

    return [
        {
            "id": v.get("id"),
            "price": v.get("price"),
            "stock_status": v.get("stock_status"),
            "attributes": v.get("attributes"),
        }
        for v in raw_variations
    ]


def fetch_products(store_url, consumer_key, consumer_secret, per_page=50):
    """
    Fetches products and extracts only the fields this project needs.
    Variable products trigger one extra request each to get real
    variation data (price/stock per variation) — the base product
    list only returns variation IDs.
    """
    url = f"{_normalize_store_url(store_url)}/wp-json/wc/v3/products"
    try:
        response = _safe_get(
            url,
            auth=(consumer_key, consumer_secret),
            params={"per_page": per_page},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_products = response.json()
    except requests.exceptions.RequestException as error:
        logger.warning("WooCommerce product fetch failed: %s", error)
        return False, "Could not fetch products from the store. Please test the connection first."
    except ValueError:
        return False, "The store returned an unexpected response format."

    products = []
    for item in raw_products:
        variation_details = None
        if item.get("type") == "variable" and item.get("variations"):
            variation_details = _fetch_variations(store_url, consumer_key, consumer_secret, item.get("id"))

        products.append({
            "external_product_id": str(item.get("id")),
            "name": item.get("name"),
            "price": item.get("price"),
            "stock_status": item.get("stock_status"),
            "description": (item.get("short_description") or item.get("description") or "")[:500],
            "sku": item.get("sku"),
            "variations": json.dumps(variation_details) if variation_details else None,
        })

    return True, products