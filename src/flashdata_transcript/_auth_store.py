"""Atomic, user-private onboarding state. Windows additionally uses user-bound DPAPI."""

from __future__ import annotations

import ctypes
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import AuthError

_HEADER = b"FLASHDATA-TRANSCRIPT-DPAPI-1\n"
_MAX_BYTES = 128 * 1024


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value: bytes) -> Blob:
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return Blob(len(value), buffer)

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source, entropy, result = blob(data), blob(b"flashdata-transcript-v1"), Blob()
    if not function(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(result)
    ):
        raise AuthError("Windows could not protect/read credentials for this user. State was kept.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


class AuthStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        path = directory or os.environ.get("FLASHDATA_TRANSCRIPT_STATE_DIR")
        self.directory = (
            Path(path).expanduser().absolute() if path else Path.home() / ".flashdata-transcript"
        )
        self.path = self.directory / "auth.state"

    @property
    def protection(self) -> str:
        return "windows-dpapi" if os.name == "nt" else "private-file-0700-0600"

    def _directory(self, *, create: bool) -> bool:
        if self.directory.is_symlink():
            raise AuthError("The authentication state directory must not be a symbolic link.")
        if create:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        elif not self.directory.exists():
            return False
        info = self.directory.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise AuthError("The authentication state path must be a private directory.")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise AuthError("Authentication state must be owned by you with directory mode 0700.")
        return True

    def _open(self, path: Path, flags: int) -> int:
        if path.is_symlink():
            raise AuthError("Authentication state files must not be symbolic links.")
        descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(descriptor)
            raise AuthError("Authentication state must be a regular file without hard links.")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            os.close(descriptor)
            raise AuthError("Authentication state files must be owned by you with mode 0600.")
        return descriptor

    def read(self) -> dict[str, Any] | None:
        if not self._directory(create=False):
            return None
        try:
            descriptor = self._open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            data = stream.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise AuthError("Authentication state exceeds its size limit. State was kept.")
        if os.name == "nt":
            if not data.startswith(_HEADER):
                raise AuthError("Windows authentication state must be DPAPI encrypted.")
            data = _dpapi(data[len(_HEADER) :], decrypt=True)
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise AuthError("Authentication state cannot be read. It was not reset.") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise AuthError("Unsupported authentication state. It was not reset.")
        return value

    def save(self, value: dict[str, Any]) -> None:
        self._directory(create=True)
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > _MAX_BYTES // 2:
            raise AuthError("Authentication state exceeds its size limit.")
        if os.name == "nt":
            data = _HEADER + _dpapi(data)
        descriptor, name = tempfile.mkstemp(prefix="auth-", suffix=".tmp", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.is_symlink():
                raise AuthError("Refusing to replace a symbolic link with authentication state.")
            os.replace(temporary, self.path)
            if os.name != "nt":
                folder = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(folder)
                finally:
                    os.close(folder)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def locked(self):
        """An OS lock releases after crashes; an old lock file never creates another trial."""
        self._directory(create=True)
        descriptor = self._open(self.directory / "auth.lock", os.O_CREAT | os.O_RDWR)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise AuthError(
                        "Another authentication command is running. Try again later."
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise AuthError(
                        "Another authentication command is running. Try again later."
                    ) from exc
            acquired = True
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
