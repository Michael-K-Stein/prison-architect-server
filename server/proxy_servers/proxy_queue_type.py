from enum import Enum


class ProxyQueueType(Enum):
    Upstream = "Upstream"
    Downstream = "Downstream"
