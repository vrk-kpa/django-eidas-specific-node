"""Storage for Light Requests and Responses backed by Apache Ignite."""
from typing import Optional

from pyignite import Client
from pyignite.cache import Cache

from eidas_node.models import LightRequest, LightResponse
from eidas_node.storage import LightStorage
from eidas_node.utils import dump_xml, parse_xml


class IgniteStorage(LightStorage):
    """
    Apache Ignite storage for Light Requests and Responses.

    :param host: Ignite service hostname or IP address.
    :param port: Ignite service port.
    :param request_cache_name: The cache where LightRequests are stored.
    :param response_cache_name: The cache where LightResponses are stored.
    :param timeout: Timeout (in seconds) for socket operations.
    """

    def __init__(self, host: str, port: int, request_cache_name: str, response_cache_name: str, timeout: int = 30):
        self.host = host
        self.port = port
        self.request_cache_name = request_cache_name
        self.response_cache_name = response_cache_name
        self.timeout = timeout
        self._client = None  # type: Optional[Client]

    def get_cache(self, cache_name: str) -> Cache:
        """Get an Ignite Cache."""
        if self._client is None:
            self._client = Client(timeout=self.timeout)
            self._client.connect(self.host, self.port)
        return self._client.get_cache(cache_name)

    def get_light_request(self, uid: str) -> Optional[LightRequest]:
        """Look up a LightRequest by a unique id."""
        data = self.get_cache(self.request_cache_name).get(uid)
        return LightRequest().load_xml(parse_xml(data)) if data is not None else None

    def get_light_response(self, uid: str) -> Optional[LightResponse]:
        """Look up a LightResponse by a unique id."""
        data = self.get_cache(self.response_cache_name).get(uid)
        return LightResponse().load_xml(parse_xml(data)) if data is not None else None

    def put_light_request(self, uid: str, request: LightRequest) -> None:
        """Store a LightRequest under a unique id."""
        self.get_cache(self.request_cache_name).put(uid, dump_xml(request.export_xml()).decode('utf-8'))

    def put_light_response(self, uid: str, response: LightResponse) -> None:
        """Store a LightRequest under a unique id."""
        self.get_cache(self.response_cache_name).put(uid, dump_xml(response.export_xml()).decode('utf-8'))