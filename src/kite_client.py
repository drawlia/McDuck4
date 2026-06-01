
import hashlib
import inspect
from urllib.parse import urljoin
from kiteconnect import KiteConnect
from src.config import Config
import logging

logger = logging.getLogger(__name__)

class KiteWrapper:
    MARKET_PROTECTION_ORDER_TYPES = {"MARKET", "SL-M"}
    MARKET_PROTECTION_AUTO = -1
    API_ROOT = "https://api.kite.trade"

    def __init__(self, access_token=None):
        self.api_key = Config.API_KEY
        self.api_secret = Config.API_SECRET
        self.access_token = access_token or Config.ACCESS_TOKEN
        self.kite = KiteConnect(api_key=self.api_key)
        self._place_order_supports_market_protection = (
            "market_protection" in inspect.signature(self.kite.place_order).parameters
        )

        if self.access_token:
            self.kite.set_access_token(self.access_token)
            logger.info("KiteConnect initialized with Access Token")
        else:
            logger.warning("No Access Token found. You may need to generate one.")

    def get_login_url(self):
        return self.kite.login_url()

    def generate_session(self, request_token):
        try:
            if not self.api_key or not self.api_secret:
                raise RuntimeError(
                    "KITE_API_KEY and KITE_API_SECRET are required to generate a session."
                )

            checksum = hashlib.sha256(
                (self.api_key + request_token + self.api_secret).encode("utf-8")
            ).hexdigest()
            data = self._request_kite_api(
                "POST",
                "/session/token",
                data={
                    "api_key": self.api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
                auth=False,
            )
            self.kite.set_access_token(data["access_token"])
            self.access_token = data["access_token"]
            logger.info("Session generated and access token set.")
            return data["access_token"]
        except Exception as e:
            logger.error(f"Error generating session: {e}")
            raise

    def _request_kite_api(self, method, path, data=None, auth=True):
        if auth and not self.access_token:
            raise RuntimeError("Kite access token is required for this API request.")

        headers = {
            "X-Kite-Version": self.kite.kite_header_version,
            "User-Agent": self.kite._user_agent(),
        }
        if auth:
            headers["Authorization"] = f"token {self.api_key}:{self.access_token}"

        response = self.kite.reqsession.request(
            method,
            urljoin(self.API_ROOT, path),
            data=data,
            headers=headers,
            timeout=self.kite.timeout,
            proxies=self.kite.proxies,
            verify=not self.kite.disable_ssl,
            allow_redirects=True,
        )
        content_type = response.headers.get("content-type", "<missing>")
        body = response.text or ""

        try:
            payload = response.json()
        except ValueError:
            preview = body[:500] if body else "<empty>"
            raise RuntimeError(
                f"Kite API returned HTTP {response.status_code} without JSON. "
                f"Content-Type: {content_type}. Body: {preview}"
            )

        if payload.get("status") == "error" or payload.get("error_type"):
            message = payload.get("message", "Unknown Kite API error")
            error_type = payload.get("error_type", "UnknownError")
            raise RuntimeError(
                f"Kite API error {response.status_code} ({error_type}): {message}"
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Kite API returned HTTP {response.status_code}. "
                f"Content-Type: {content_type}. Body: {body[:500]}"
            )

        return payload.get("data", payload)

    def get_quote(self, symbols):
        try:
            return self.kite.quote(symbols)
        except Exception as e:
            logger.error(f"Error fetching quote for {symbols}: {e}")
            return {}

    def place_order(
        self,
        tradingsymbol,
        exchange,
        transaction_type,
        quantity,
        order_type,
        product,
        price=None,
        trigger_price=None,
        variety="regular",
        market_protection=True,
    ):
        try:
            params = {
                "variety": variety,
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": order_type,
                "product": product,
                "price": price,
                "trigger_price": trigger_price,
            }

            if order_type.upper() in self.MARKET_PROTECTION_ORDER_TYPES:
                params["market_protection"] = self._normalize_market_protection(
                    market_protection
                )

            params = {key: value for key, value in params.items() if value is not None}
            order_id = self._submit_order(params)
            logger.info(f"Order placed. ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def _normalize_market_protection(self, market_protection):
        if market_protection is True:
            return self.MARKET_PROTECTION_AUTO
        if market_protection is False:
            return 0
        return market_protection

    def _submit_order(self, params):
        if (
            "market_protection" in params
            and not self._place_order_supports_market_protection
        ):
            return self.kite._post(
                "order.place",
                url_args={"variety": params["variety"]},
                params=params,
            )["order_id"]

        return self.kite.place_order(**params)


    def get_orders(self):
        try:
            return self.kite.orders()
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []

    def get_historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
        """
        Fetch historical data.
        """
        try:
            return self.kite.historical_data(instrument_token, from_date, to_date, interval, continuous, oi)
        except Exception as e:
            logger.error(f"Error fetching historical data for {instrument_token}: {e}")
            return []

    def login_flow(self):
        """
        Orchestrates the manual login flow.
        1. Checks if access_token is already set.
        2. If not, prints login URL.
        3. Waits for user input (request_token).
        4. Generates session.
        """
        if self.access_token:
            logger.info("Access token found in environment. Testing validity...")
            try:
                self._request_kite_api("GET", "/user/profile")
                logger.info("Access token is valid.")
                return
            except Exception as e:
                logger.warning(f"Existing access token invalid or unreachable: {e}")
        
        url = self.get_login_url()
        print(f"\n[LOGIN REQUIRED] Open this URL in your browser:\n{url}\n")
        print("After logging in, you will be redirected to a URL with a 'request_token' parameter.")
        request_token = input("Paste the 'request_token' value here: ").strip()

        if request_token:
            self.generate_session(request_token)
            print("\n[SUCCESS] Login successful. Access token generated.\n")
        else:
            logger.error("No request token provided.")
