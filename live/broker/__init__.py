from .base import Broker, Order  # noqa: F401
from .paper import PaperBroker  # noqa: F401


def make_broker(store, settings=None):
    from ..settings import SETTINGS
    s = settings or SETTINGS
    if s.paper:
        return PaperBroker(store, s)
    from .alpaca import AlpacaBroker
    return AlpacaBroker(store, s)
