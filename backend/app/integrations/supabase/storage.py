"""Supabase Storage 연동 (v0.4 작품 사진).

권한 모델
- 백엔드는 service_role 키를 쓰지 않는다. 모든 Storage 호출은 **요청한 사용자의 access token**과
  공개 anon 키(apikey 헤더)로 한다. → Storage가 storage.objects RLS 정책으로 다시 권한을
  검사한다 (backend/supabase/storage-setup.sql). 백엔드 권한 검사가 1차, Storage RLS가 2차 방어.
- 버킷은 비공개. 파일은 짧은 만료의 Signed URL로만 내려받는다.

테스트는 `StorageClient` 프로토콜을 구현한 가짜 객체를 `app.state.storage`에 넣어
외부 호출 없이 실행한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Storage 호출 실패 (네트워크, 5xx, 권한 거부 등). 메시지에 토큰·URL 쿼리를 넣지 않는다."""


class StorageObjectNotFound(StorageError):
    """객체가 없음 (아직 업로드하지 않았거나 이미 삭제됨)."""


class StorageObjectTooLarge(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class SignedUpload:
    """클라이언트가 파일을 직접 올릴 Signed upload URL (supabase-js `uploadToSignedUrl`용)."""

    url: str
    token: str


class StorageClient(Protocol):
    bucket: str

    async def create_upload_url(self, path: str, *, access_token: str) -> SignedUpload: ...

    async def download(self, path: str, *, access_token: str, max_bytes: int) -> bytes: ...

    async def create_signed_urls(
        self, paths: list[str], *, access_token: str, expires_in: int
    ) -> dict[str, str]: ...

    async def delete(self, paths: list[str], *, access_token: str) -> None: ...

    async def upload(self, path: str, data: bytes, *, content_type: str, access_token: str) -> None:
        """서버가 만든 파일 업로드 (v0.8 공유용 파생 이미지). 사용자 토큰 + Storage RLS."""
        ...


class SupabaseStorage:
    def __init__(
        self,
        *,
        api_url: str,
        anon_key: str,
        bucket: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,  # 테스트용 MockTransport
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.bucket = bucket
        self._anon_key = anon_key
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {access_token}"}

    def _object_url(self, prefix: str, path: str) -> str:
        return f"{self.api_url}/{prefix}/{self.bucket}/{quote(path)}"

    def _absolute(self, relative: str) -> str:
        # Storage API는 "/object/sign/..." 형태의 상대 경로를 돌려준다
        return f"{self.api_url}/{relative.lstrip('/')}"

    async def _request(self, method: str, url: str, access_token: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
        headers = self._headers(access_token) | kwargs.pop("headers", {})
        try:
            async with self._client() as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("storage request failed", extra={"error_type": type(exc).__name__})
            raise StorageError("Storage request failed") from None
        if response.status_code in (400, 404) and "not found" in response.text.lower():
            raise StorageObjectNotFound("Object not found")
        if response.status_code >= 400:
            logger.warning("storage error response", extra={"status": response.status_code})
            raise StorageError(f"Storage responded with {response.status_code}")
        return response

    async def create_upload_url(self, path: str, *, access_token: str) -> SignedUpload:
        response = await self._request(
            "POST", self._object_url("object/upload/sign", path), access_token
        )
        relative = response.json()["url"]
        token = httpx.URL(self._absolute(relative)).params.get("token")
        if not token:
            raise StorageError("Storage did not return an upload token")
        return SignedUpload(url=self._absolute(relative), token=token)

    async def download(self, path: str, *, access_token: str, max_bytes: int) -> bytes:
        url = self._object_url("object/authenticated", path)
        try:
            async with (
                self._client() as client,
                client.stream("GET", url, headers=self._headers(access_token)) as response,
            ):
                if response.status_code in (400, 404):
                    raise StorageObjectNotFound("Object not found")
                if response.status_code >= 400:
                    raise StorageError(f"Storage responded with {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageObjectTooLarge("Object exceeds the size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            logger.warning("storage download failed", extra={"error_type": type(exc).__name__})
            raise StorageError("Storage request failed") from None

    async def create_signed_urls(
        self, paths: list[str], *, access_token: str, expires_in: int
    ) -> dict[str, str]:
        if not paths:
            return {}
        response = await self._request(
            "POST",
            f"{self.api_url}/object/sign/{self.bucket}",
            access_token,
            json={"expiresIn": expires_in, "paths": paths},
        )
        result: dict[str, str] = {}
        for item in response.json():
            if item.get("signedURL") and not item.get("error"):
                result[item["path"]] = self._absolute(item["signedURL"])
        return result

    async def upload(self, path: str, data: bytes, *, content_type: str, access_token: str) -> None:
        await self._request(
            "POST",
            self._object_url("object", path),
            access_token,
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )

    async def delete(self, paths: list[str], *, access_token: str) -> None:
        if paths:
            await self._request(
                "DELETE",
                f"{self.api_url}/object/{self.bucket}",
                access_token,
                json={"prefixes": paths},
            )


class AudioFetcher(Protocol):
    """Worker가 Signed URL로 음성 파일을 내려받는다 (사용자 토큰·service_role 없이)."""

    async def fetch(self, url: str, *, max_bytes: int) -> bytes: ...


class HttpSignedUrlFetcher:
    def __init__(
        self, *, timeout: float, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout = timeout
        self._transport = transport

    async def fetch(self, url: str, *, max_bytes: int) -> bytes:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code in (400, 404):
                    raise StorageObjectNotFound("Object not found or URL expired")
                if response.status_code >= 400:
                    raise StorageError(f"Storage responded with {response.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageObjectTooLarge("Object exceeds the size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            # URL에는 서명 토큰이 있으므로 로그에 남기지 않는다
            logger.warning("signed url download failed", extra={"error_type": type(exc).__name__})
            raise StorageError("Storage request failed") from None


def build_storage(settings: Settings, bucket: str | None = None) -> StorageClient | None:
    """버킷 하나당 클라이언트 하나. 기본은 작품 사진 버킷 (`STORAGE_BUCKET`)."""
    if not settings.storage_configured:
        return None
    assert settings.storage_api_url and settings.supabase_anon_key
    return SupabaseStorage(
        api_url=settings.storage_api_url,
        anon_key=settings.supabase_anon_key.get_secret_value(),
        bucket=bucket or settings.storage_bucket,
        timeout=settings.storage_timeout_seconds,
    )
