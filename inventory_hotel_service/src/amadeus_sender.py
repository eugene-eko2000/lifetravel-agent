from typing import Any, Awaitable, Callable

import httpx

from amadeus_interval import AmadeusRequestRateLimit
from cfg import Cfg
from debug_messages import DebugPublisher, emit_debug_message

OnHotelResponse = Callable[[], Awaitable[None]]


class AmadeusSender:
    def __init__(
        self,
        cfg: Cfg | None = None,
        *,
        request_rate_limit: AmadeusRequestRateLimit | None = None,
    ) -> None:
        self._cfg = cfg or Cfg.from_env()
        self._bearer_token: str | None = None
        self._request_rate_limit = request_rate_limit

    async def _get_amadeus_bearer_token(self) -> str:
        if self._bearer_token:
            return self._bearer_token

        if not self._cfg.amadeus_client_id or not self._cfg.amadeus_client_secret:
            raise ValueError(
                "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set"
            )

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._cfg.amadeus_client_id,
            "client_secret": self._cfg.amadeus_client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        if self._request_rate_limit is not None:
            await self._request_rate_limit.acquire()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._cfg.amadeus_token_url,
                data=payload,
                headers=headers,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("Failed to retrieve Amadeus access token")
            self._bearer_token = token
            return token

    async def _authorized_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged_headers: dict[str, str] = {}
        if isinstance(headers, dict):
            merged_headers = {str(k): str(v) for k, v in headers.items()}

        token = await self._get_amadeus_bearer_token()
        merged_headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            if self._request_rate_limit is not None:
                await self._request_rate_limit.acquire()
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_payload,
                headers=merged_headers,
            )
            if response.status_code == 401:
                self._bearer_token = None
                refreshed_token = await self._get_amadeus_bearer_token()
                merged_headers["Authorization"] = f"Bearer {refreshed_token}"
                if self._request_rate_limit is not None:
                    await self._request_rate_limit.acquire()
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_payload,
                    headers=merged_headers,
                )
            response.raise_for_status()
            return response.json()

    async def send_hotels_list(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
        *,
        on_response: OnHotelResponse | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._authorized_request(
                "GET",
                self._cfg.amadeus_hotels_list_url,
                params=query_params,
                headers=headers,
            )
        finally:
            if on_response is not None:
                await on_response()

    async def send_hotels_list_by_geocode(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
        *,
        on_response: OnHotelResponse | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._authorized_request(
                "GET",
                self._cfg.amadeus_hotels_list_by_geocode_url,
                params=query_params,
                headers=headers,
            )
        finally:
            if on_response is not None:
                await on_response()

    async def send_hotels_offers(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
        *,
        debug_publisher: DebugPublisher | None = None,
        request_id: str | None = None,
        debug_extra: dict[str, Any] | None = None,
        on_response: OnHotelResponse | None = None,
    ) -> dict[str, Any]:
        try:
            try:
                return await self._authorized_request(
                    "GET",
                    self._cfg.amadeus_hotels_offers_url,
                    params=query_params,
                    headers=headers,
                )
            except Exception as error:
                # Published on failure from _authorized_request (e.g. HTTP 429).
                payload: dict[str, Any] = {}
                if debug_extra:
                    payload.update(debug_extra)
                payload["error"] = str(error)
                await emit_debug_message(
                    debug_publisher,
                    request_id,
                    "Failed to fetch hotels offers chunk",
                    level="error",
                    payload=payload,
                )
                raise
        finally:
            if on_response is not None:
                await on_response()
