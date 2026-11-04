"""SupabaseStorage HTTP 클라이언트 (httpx MockTransport, 실제 Supabase 미접속)."""

import json

import httpx
import pytest

from app.integrations.supabase.storage import (
    StorageError,
    StorageObjectNotFound,
    StorageObjectTooLarge,
    SupabaseStorage,
    build_storage,
)
from tests.conftest import make_settings

API = "https://proj.supabase.co/storage/v1"
PATH = "user-1/art-2/photo-3.png"


def _storage(handler) -> tuple[SupabaseStorage, list[httpx.Request]]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    storage = SupabaseStorage(
        api_url=API,
        anon_key="anon-public",
        bucket="artworks",
        timeout=1,
        transport=httpx.MockTransport(record),
    )
    return storage, seen


async def test_upload_url_uses_user_token_and_parses_response() -> None:
    storage, seen = _storage(
        lambda r: httpx.Response(
            200, json={"url": f"/object/upload/sign/artworks/{PATH}?token=abc.def"}
        )
    )
    signed = await storage.create_upload_url(PATH, access_token="user-jwt")
    assert signed.token == "abc.def"
    assert signed.url == f"{API}/object/upload/sign/artworks/{PATH}?token=abc.def"
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{API}/object/upload/sign/artworks/{PATH}"
    assert request.headers["authorization"] == "Bearer user-jwt"
    assert request.headers["apikey"] == "anon-public"


async def test_signed_urls_batch_skips_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"expiresIn": 300, "paths": ["a.png", "b.png"]}
        return httpx.Response(
            200,
            json=[
                {
                    "path": "a.png",
                    "signedURL": "/object/sign/artworks/a.png?token=t",
                    "error": None,
                },
                {"path": "b.png", "signedURL": None, "error": "Either the object does not exist"},
            ],
        )

    storage, _ = _storage(handler)
    urls = await storage.create_signed_urls(["a.png", "b.png"], access_token="jwt", expires_in=300)
    assert urls == {"a.png": f"{API}/object/sign/artworks/a.png?token=t"}


async def test_download_limits_and_errors() -> None:
    storage, _ = _storage(lambda r: httpx.Response(200, content=b"x" * 50))
    assert await storage.download(PATH, access_token="jwt", max_bytes=100) == b"x" * 50
    with pytest.raises(StorageObjectTooLarge):
        await storage.download(PATH, access_token="jwt", max_bytes=10)

    missing, _ = _storage(lambda r: httpx.Response(400, json={"error": "not_found"}))
    with pytest.raises(StorageObjectNotFound):
        await missing.download(PATH, access_token="jwt", max_bytes=10)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    broken, _ = _storage(boom)
    with pytest.raises(StorageError):
        await broken.download(PATH, access_token="jwt", max_bytes=10)
    with pytest.raises(StorageError):
        await broken.create_upload_url(PATH, access_token="jwt")


async def test_delete_and_server_errors() -> None:
    storage, seen = _storage(lambda r: httpx.Response(200, json=[]))
    await storage.delete([PATH], access_token="jwt")
    assert seen[0].method == "DELETE" and json.loads(seen[0].content) == {"prefixes": [PATH]}
    await storage.delete([], access_token="jwt")  # 빈 목록은 호출하지 않음
    assert len(seen) == 1

    forbidden, _ = _storage(lambda r: httpx.Response(403, json={"error": "Unauthorized"}))
    with pytest.raises(StorageError) as exc:
        await forbidden.delete([PATH], access_token="secret-jwt")
    assert "secret-jwt" not in str(exc.value)  # 오류 메시지에 토큰 미포함


def test_build_storage_requires_url_and_anon_key() -> None:
    assert build_storage(make_settings()) is None
    assert build_storage(make_settings(supabase_url="https://proj.supabase.co")) is None
    storage = build_storage(
        make_settings(supabase_url="https://proj.supabase.co", supabase_anon_key="anon")
    )
    assert isinstance(storage, SupabaseStorage)
    assert storage.api_url == API and storage.bucket == "artworks"
