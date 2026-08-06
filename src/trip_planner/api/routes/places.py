import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from trip_planner.config import get_settings
from trip_planner.services.http_client import get_http_client

router = APIRouter(prefix="/places", tags=["places"])

_settings = get_settings()
_PHOTO_MEDIA_BASE_URL = "https://places.googleapis.com/v1"
_DEFAULT_MAX_WIDTH_PX = 800


@router.get("/photos/{photo_reference:path}")
async def get_place_photo(
    photo_reference: str, max_width_px: int = _DEFAULT_MAX_WIDTH_PX
) -> RedirectResponse:
    """Redirect the caller to the actual Google-hosted photo for a place.

    Google's photo media endpoint itself replies with a 302 to a signed, keyless CDN URL, so
    this forwards that redirect target to the client instead of proxying image bytes through
    this app — keeping the Google API key server-side without paying for a full media proxy.
    """
    client = get_http_client()
    url = f"{_PHOTO_MEDIA_BASE_URL}/{photo_reference}/media"
    params = {"maxWidthPx": max_width_px, "key": _settings.google_places_api_key}

    try:
        response = await client.get(url, params=params, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Photo unavailable"
        ) from exc

    location = response.headers.get("location")
    if response.status_code != status.HTTP_302_FOUND or location is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Photo unavailable")

    return RedirectResponse(url=location, status_code=status.HTTP_302_FOUND)
