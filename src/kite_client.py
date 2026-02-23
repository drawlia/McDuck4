
from kiteconnect import KiteConnect
from src.config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KiteWrapper:
    def __init__(self):
        self.api_key = Config.API_KEY
        self.api_secret = Config.API_SECRET
        self.access_token = Config.ACCESS_TOKEN
        self.kite = KiteConnect(api_key=self.api_key)

        if self.access_token:
            self.kite.set_access_token(self.access_token)
            logger.info("KiteConnect initialized with Access Token")
        else:
            logger.warning("No Access Token found. You may need to generate one.")

    def get_login_url(self):
        return self.kite.login_url()

    def generate_session(self, request_token):
        try:
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            self.kite.set_access_token(data["access_token"])
            logger.info(f"Session generated. Access Token: {data['access_token']}")
            return data["access_token"]
        except Exception as e:
            logger.error(f"Error generating session: {e}")
            raise

    def get_quote(self, symbols):
        try:
            return self.kite.quote(symbols)
        except Exception as e:
            logger.error(f"Error fetching quote for {symbols}: {e}")
            return {}

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, order_type, product, price=None, trigger_price=None, variety="regular"):
        try:
            order_id = self.kite.place_order(
                variety=variety,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product=product,
                price=price,
                trigger_price=trigger_price
            )
            logger.info(f"Order placed. ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None


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
                self.kite.profile() # Simple call to check if token is valid
                logger.info("Access token is valid.")
                return
            except Exception as e:
                logger.warning(f"Existing access token invalid: {e}")
        
        url = self.get_login_url()
        print(f"\n[LOGIN REQUIRED] Open this URL in your browser:\n{url}\n")
        print("After logging in, you will be redirected to a URL with a 'request_token' parameter.")
        request_token = input("Paste the 'request_token' value here: ").strip()

        if request_token:
            self.generate_session(request_token)
            print("\n[SUCCESS] Login successful. Access token generated.\n")
        else:
            logger.error("No request token provided.")
