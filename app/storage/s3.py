"""S3 / MinIO wrapper.

Thin async wrapper around aioboto3. All callers use the canonical key
builders in ``app.storage.paths`` and just pass bytes/streams here.

There's also a ``MemoryObjectStore`` fallback selected when the env var
``CPA_S3_BACKEND=memory`` is set — used by unit tests so they don't need
a live MinIO.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from app.config import get_settings


class ObjectStore(Protocol):
    async def put(self, key: str, body: bytes, *, content_type: str | None = ...) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def head(self, key: str) -> dict[str, Any] | None: ...


class MemoryObjectStore:
    """In-process store for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, str | None]] = {}

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None:
        self._data[key] = (body, content_type)

    async def get(self, key: str) -> bytes:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key][0]

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def head(self, key: str) -> dict[str, Any] | None:
        if key not in self._data:
            return None
        body, ctype = self._data[key]
        return {"size": len(body), "content_type": ctype}


class S3ObjectStore:
    """Real S3/MinIO backed via aioboto3."""

    def __init__(self) -> None:
        import aioboto3  # local import — only when actually used

        settings = get_settings()
        self._session = aioboto3.Session()
        self._endpoint = settings.s3_endpoint_url
        self._access_key = settings.s3_access_key.get_secret_value()
        self._secret_key = settings.s3_secret_key.get_secret_value()
        self._region = settings.s3_region
        self._bucket = settings.s3_bucket

    def _client(self) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        )

    async def put(self, key: str, body: bytes, *, content_type: str | None = None) -> None:
        async with self._client() as s3:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": body}
            if content_type:
                kwargs["ContentType"] = content_type
            await s3.put_object(**kwargs)

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def head(self, key: str) -> dict[str, Any] | None:
        async with self._client() as s3:
            try:
                resp = await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception:
                return None
            return {"size": resp.get("ContentLength"), "content_type": resp.get("ContentType")}


_singleton: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _singleton
    if _singleton is None:
        backend = os.environ.get("CPA_S3_BACKEND", "s3").lower()
        _singleton = MemoryObjectStore() if backend == "memory" else S3ObjectStore()
    return _singleton


def reset_object_store() -> None:  # for tests
    global _singleton
    _singleton = None
