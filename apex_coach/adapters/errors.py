"""Shared failure vocabulary for every adapter (ADR-0002, ADR-0010).

Real adapters raise these to classify a transport failure before converting
it into their own graceful-degradation output. Adapter-specific failure
modes with no cross-adapter analog subclass the shared base rather than
living here — the hierarchy is common, the leaves are adapter-specific.
"""


class AdapterError(Exception):
    pass


class AdapterUnavailableError(AdapterError):
    pass


class AdapterTimeoutError(AdapterError):
    pass


class AdapterMalformedResponseError(AdapterError):
    pass
