from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlencode

from palette_api.domain import (
    DataSource,
    ListeningHistory,
    ListeningPeriod,
    ProfileDetails,
    Track,
)


LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
# Last.fm returns a ranked page for each period.  The API v2 uses a larger
# candidate page so the local snapshot can find documented recordings beyond
# the first 50 ranks without turning every candidate into hydration work.
TOP_TRACK_LIMIT = 200


class LastFmError(Exception):
    """Base error for failures owned by the Last.fm adapter."""


class LastFmConfigurationError(LastFmError):
    pass


class LastFmProfileNotFoundError(LastFmError):
    pass


class LastFmRateLimitError(LastFmError):
    pass


class LastFmUnavailableError(LastFmError):
    pass


class LastFmInvalidResponseError(LastFmError):
    pass


@dataclass(frozen=True, slots=True)
class JsonHttpResponse:
    status_code: int
    body: object
    retry_after_seconds: int | None = None


class AsyncJsonTransport(Protocol):
    async def get_json(self, url: str) -> JsonHttpResponse: ...


class WorkersFetchJsonTransport:
    """HTTP transport backed by the native asynchronous Workers Fetch API."""

    async def get_json(self, url: str) -> JsonHttpResponse:
        # This import only exists inside the Pyodide-based Workers runtime.
        from workers import fetch

        try:
            response = await fetch(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "timbre-palette-api/0.1",
                },
            )
            body = await response.json()
        except Exception as error:
            raise LastFmUnavailableError(
                "Could not access the Last.fm service."
            ) from error

        return JsonHttpResponse(status_code=int(response.status), body=body)


class LastFmListeningHistoryProvider:
    def __init__(
        self,
        api_key: str,
        transport: AsyncJsonTransport,
        limit: int = TOP_TRACK_LIMIT,
    ) -> None:
        normalized_api_key = api_key.strip()
        if not normalized_api_key:
            raise LastFmConfigurationError("The Last.fm API key was not configured.")
        if not 1 <= limit <= TOP_TRACK_LIMIT:
            raise ValueError(f"limit must be between 1 and {TOP_TRACK_LIMIT}.")

        self._api_key = normalized_api_key
        self._transport = transport
        self._limit = limit

    async def get_history(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> ListeningHistory:
        response = await self._transport.get_json(
            self._build_top_tracks_url(username, period)
        )
        payload = response.body

        if isinstance(payload, Mapping) and "error" in payload:
            self._raise_api_error(payload, username)
        if response.status_code >= 400:
            raise LastFmUnavailableError(
                f"Last.fm responded with HTTP {response.status_code}."
            )
        if not isinstance(payload, Mapping):
            raise LastFmInvalidResponseError(
                "Last.fm returned an unexpected JSON document."
            )

        top_tracks = payload.get("toptracks")
        if not isinstance(top_tracks, Mapping):
            raise LastFmInvalidResponseError(
                "Last.fm did not return the expected toptracks collection."
            )

        canonical_username = self._canonical_username(top_tracks, username)
        tracks = self._parse_tracks(top_tracks.get("track", []))
        profile = await self._get_profile(canonical_username)
        return ListeningHistory(
            username=canonical_username,
            period=period,
            tracks=tracks,
            history_source=DataSource.LASTFM,
            instrumentation_source=DataSource.MOCK,
            profile=profile,
        )

    def _build_top_tracks_url(
        self,
        username: str,
        period: ListeningPeriod,
    ) -> str:
        query = urlencode(
            {
                "method": "user.gettoptracks",
                "user": username,
                "api_key": self._api_key,
                "format": "json",
                "period": period.value,
                "limit": str(self._limit),
                "page": "1",
            }
        )
        return f"{LASTFM_API_URL}?{query}"

    def _build_user_info_url(self, username: str) -> str:
        query = urlencode(
            {
                "method": "user.getinfo",
                "user": username,
                "api_key": self._api_key,
                "format": "json",
            }
        )
        return f"{LASTFM_API_URL}?{query}"

    async def _get_profile(self, username: str) -> ProfileDetails | None:
        """Read optional profile metadata without compromising the history read."""
        try:
            response = await self._transport.get_json(
                self._build_user_info_url(username)
            )
        except LastFmError:
            return None

        if response.status_code >= 400 or not isinstance(response.body, Mapping):
            return None
        if "error" in response.body:
            return None

        raw_user = response.body.get("user")
        if not isinstance(raw_user, Mapping):
            return None
        return self._parse_profile(raw_user)

    @classmethod
    def _parse_profile(cls, raw_user: Mapping[object, object]) -> ProfileDetails:
        return ProfileDetails(
            profile_url=cls._optional_text(raw_user.get("url")),
            avatar_url=cls._parse_avatar_url(raw_user.get("image")),
            realname=cls._optional_text(raw_user.get("realname")),
            registered=cls._parse_registered(raw_user.get("registered")),
        )

    @classmethod
    def _parse_registered(cls, value: object) -> str | None:
        """Return Last.fm's registration time as an ISO 8601 UTC string."""
        timestamp: object = None
        text: object = value
        if isinstance(value, Mapping):
            timestamp = value.get("unixtime")
            text = value.get("#text") or value.get("text")

        if timestamp is not None:
            try:
                unix_time = int(str(timestamp).strip())
                if unix_time >= 0:
                    return datetime.fromtimestamp(unix_time, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass

        raw_text = cls._optional_text(text)
        if not raw_text:
            return None
        try:
            parsed = datetime.fromisoformat(raw_text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @classmethod
    def _parse_avatar_url(cls, value: object) -> str | None:
        candidates: list[str] = []
        raw_values = value if isinstance(value, list) else [value]
        for raw_value in raw_values:
            if isinstance(raw_value, Mapping):
                raw_value = raw_value.get("#text") or raw_value.get("url")
            candidate = cls._optional_text(raw_value)
            if candidate and candidate.startswith(("http://", "https://")):
                candidates.append(candidate)
        return candidates[-1] if candidates else None

    def _parse_tracks(self, raw_tracks: object) -> tuple[Track, ...]:
        if isinstance(raw_tracks, Mapping):
            candidates: list[object] = [raw_tracks]
        elif isinstance(raw_tracks, list):
            candidates = raw_tracks
        else:
            raise LastFmInvalidResponseError(
                "The Last.fm track collection has an unexpected format."
            )

        tracks = tuple(
            parsed
            for candidate in candidates[: self._limit]
            if (parsed := self._parse_track(candidate)) is not None
        )
        if candidates and not tracks:
            raise LastFmInvalidResponseError(
                "No valid tracks were found in the Last.fm response."
            )
        return tracks

    @staticmethod
    def _parse_track(raw_track: object) -> Track | None:
        if not isinstance(raw_track, Mapping):
            return None

        title = LastFmListeningHistoryProvider._optional_text(raw_track.get("name"))
        artist_data = raw_track.get("artist")
        if isinstance(artist_data, Mapping):
            artist = LastFmListeningHistoryProvider._optional_text(
                artist_data.get("name")
            )
            artist_mbid = LastFmListeningHistoryProvider._optional_text(
                artist_data.get("mbid")
            )
        else:
            artist = LastFmListeningHistoryProvider._optional_text(artist_data)
            artist_mbid = None

        try:
            play_count = int(str(raw_track.get("playcount", "0")))
        except (TypeError, ValueError):
            return None

        if not title or not artist or play_count < 0:
            return None

        album = raw_track.get("album")
        release_mbid = (
            LastFmListeningHistoryProvider._optional_text(album.get("mbid"))
            if isinstance(album, Mapping)
            else None
        )

        return Track(
            title=title,
            artist=artist,
            play_count=play_count,
            mbid=LastFmListeningHistoryProvider._optional_text(raw_track.get("mbid")),
            lastfm_url=LastFmListeningHistoryProvider._optional_text(
                raw_track.get("url")
            ),
            release_mbid=release_mbid,
            artist_mbid=artist_mbid,
        )

    @staticmethod
    def _canonical_username(top_tracks: Mapping[object, object], fallback: str) -> str:
        attributes = top_tracks.get("@attr")
        if not isinstance(attributes, Mapping):
            return fallback
        return (
            LastFmListeningHistoryProvider._optional_text(attributes.get("user"))
            or fallback
        )

    @staticmethod
    def _raise_api_error(payload: Mapping[object, object], username: str) -> None:
        try:
            code = int(str(payload.get("error")))
        except (TypeError, ValueError):
            code = 0
        message = str(payload.get("message", "Unknown Last.fm error."))
        normalized_message = message.casefold()

        if code == 6 and "user" in normalized_message and "not found" in normalized_message:
            raise LastFmProfileNotFoundError(username)
        if code in {4, 10, 26}:
            raise LastFmConfigurationError(message)
        if code == 29:
            raise LastFmRateLimitError(message)
        if code in {8, 11, 16}:
            raise LastFmUnavailableError(message)
        raise LastFmInvalidResponseError(message)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _optional_nonnegative_int(value: object) -> int | None:
        try:
            normalized = int(str(value))
        except (TypeError, ValueError):
            return None
        return normalized if normalized >= 0 else None
