"""Normalize user inputs before making a request."""

import re
from collections.abc import Sequence
from urllib.parse import parse_qs, urlsplit

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_LANGUAGE = re.compile(r"[A-Za-z0-9-]{1,35}\Z")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_EMBED_HOSTS = {"youtube-nocookie.com", "www.youtube-nocookie.com"}


def video_id(value: str) -> str:
    """Accept an ID or a YouTube watch, Shorts, live, embed, or short URL."""
    if not isinstance(value, str):
        raise ValueError("Provide a YouTube video ID or URL.")
    value = value.strip()
    if _VIDEO_ID.fullmatch(value):
        return value
    if "://" not in value:
        value = "https://" + value
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or url.username or url.password:
        raise ValueError("Provide a YouTube video ID or an http(s) YouTube URL.")
    host = (url.hostname or "").lower()
    parts = url.path.strip("/").split("/")
    candidate = ""
    if host in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        candidate = parts[0]
    elif host in _YOUTUBE_HOSTS:
        if parts == ["watch"]:
            ids = parse_qs(url.query).get("v", [])
            if len(ids) == 1:
                candidate = ids[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            candidate = parts[1]
    elif host in _EMBED_HOSTS and len(parts) == 2 and parts[0] == "embed":
        candidate = parts[1]
    if not _VIDEO_ID.fullmatch(candidate):
        raise ValueError("Use an 11-character video ID or a YouTube video URL, not a playlist.")
    return candidate


def language_code(value: str) -> str:
    if not isinstance(value, str) or not _LANGUAGE.fullmatch(value):
        raise ValueError("Use a language code such as en, es, zh-Hans, or en-orig.")
    return value


def language_codes(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("Pass a list of 1 to 10 distinct language codes.")
    result = [language_code(value) for value in values]
    if not 1 <= len(result) <= 10 or len(set(result)) != len(result):
        raise ValueError("Pass a list of 1 to 10 distinct language codes.")
    return result


def caption_origin(auto: bool) -> bool:
    if not isinstance(auto, bool):
        raise ValueError("auto must be True for automatic captions or False for manual captions.")
    return auto
