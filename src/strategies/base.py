
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    def __init__(self, kite_client, trade_manager):
        self.kite_client = kite_client
        self.trade_manager = trade_manager

    @abstractmethod
    def on_tick(self):
        """
        Called periodically to check for entry signals.
        """
        pass
