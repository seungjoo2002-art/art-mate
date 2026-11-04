"""테스트용 Supabase Storage 대체 구현 (메모리). 실제 Supabase에 접근하지 않는다."""

import io
from dataclasses import dataclass, field

from PIL import Image

from app.integrations.supabase.storage import (
    SignedUpload,
    StorageError,
    StorageObjectNotFound,
    StorageObjectTooLarge,
)


@dataclass
class FakeStorage:
    bucket: str = "artworks"
    objects: dict[str, bytes] = field(default_factory=dict)
    # 실패시킬 동작: "upload_url", "download", "sign", "delete"
    fail: set[str] = field(default_factory=set)
    # (동작, 경로들, 사용한 access token) 기록 → 사용자 토큰 전달 확인용
    calls: list[tuple[str, tuple[str, ...], str]] = field(default_factory=list)

    def _check(self, op: str, paths: tuple[str, ...], token: str) -> None:
        self.calls.append((op, paths, token))
        if op in self.fail:
            raise StorageError(f"simulated {op} failure")

    def put(self, path: str, data: bytes) -> None:
        """클라이언트가 Signed upload URL로 파일을 올린 것처럼 저장."""
        self.objects[path] = data

    async def create_upload_url(self, path: str, *, access_token: str) -> SignedUpload:
        self._check("upload_url", (path,), access_token)
        return SignedUpload(
            url=f"https://storage.test/object/upload/sign/{self.bucket}/{path}?token=tok",
            token=f"tok-{path}",
        )

    async def download(self, path: str, *, access_token: str, max_bytes: int) -> bytes:
        self._check("download", (path,), access_token)
        if path not in self.objects:
            raise StorageObjectNotFound("missing")
        data = self.objects[path]
        if len(data) > max_bytes:
            raise StorageObjectTooLarge("too large")
        return data

    async def create_signed_urls(
        self, paths: list[str], *, access_token: str, expires_in: int
    ) -> dict[str, str]:
        self._check("sign", tuple(paths), access_token)
        return {
            p: f"https://storage.test/object/sign/{self.bucket}/{p}?token=signed&e={expires_in}"
            for p in paths
            if p in self.objects
        }

    async def delete(self, paths: list[str], *, access_token: str) -> None:
        self._check("delete", tuple(paths), access_token)
        for path in paths:
            self.objects.pop(path, None)


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (32, 24), color: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()
