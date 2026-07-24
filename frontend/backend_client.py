"""Thin HTTP client for talking to the AgentCare backend.

This is the ONLY way the frontend touches backend data — no backend Python
modules are ever imported here. Every call goes over real HTTP, the same
contract any third-party client would use.
"""

import httpx

from config import get_settings


class BackendAPIError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class BackendClient:
    def __init__(self, token: str | None = None):
        self.token = token
        self.base_url = get_settings().backend_api_url

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def get(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            response = await self._send(client.get, path, params=params, headers=self._headers())
        return self._handle(response)

    async def post(
        self, path: str, *, json: dict | None = None, data: dict | None = None, files=None, timeout: float = 30
    ):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            response = await self._send(
                client.post, path, json=json, data=data, files=files, headers=self._headers()
            )
        return self._handle(response)

    async def patch(self, path: str, *, json: dict | None = None, params: dict | None = None):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            response = await self._send(client.patch, path, json=json, params=params, headers=self._headers())
        return self._handle(response)

    @staticmethod
    async def _send(method, *args, **kwargs) -> httpx.Response:
        """Turn network-level failures (timeout, connection refused, DNS,
        etc.) into the same BackendAPIError every route already handles,
        instead of letting a raw httpx exception crash the page."""
        try:
            return await method(*args, **kwargs)
        except httpx.TimeoutException as exc:
            raise BackendAPIError(504, "The backend took too long to respond. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise BackendAPIError(502, "Could not reach the backend. Please try again shortly.") from exc

    @staticmethod
    def _handle(response: httpx.Response):
        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                detail = body.get("detail", detail)
            except ValueError:
                pass
            raise BackendAPIError(response.status_code, str(detail))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
