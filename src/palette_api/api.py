import json
from typing import Annotated

from collections.abc import Mapping

from fastapi import Depends, FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from palette_api.application import (
    EmptyListeningHistoryError,
    PaletteService,
)
from palette_api.domain import ListeningPeriod
from palette_api.lastfm import (
    LastFmConfigurationError,
    LastFmInvalidResponseError,
    LastFmListeningHistoryProvider,
    LastFmProfileNotFoundError,
    LastFmRateLimitError,
    LastFmUnavailableError,
    WorkersFetchJsonTransport,
)
from palette_api.catalog import (
    D1InstrumentCatalog,
    D1InstrumentationProvider,
    InstrumentCatalogProvider,
    _get_val,
)
from palette_api.enrichment import D1QueueEnrichmentScheduler
from palette_api.image_catalog import DEFAULT_IMAGE_CATALOG, InstrumentImageCatalog
from palette_api.mocks import (
    MockInstrumentCatalog,
    MockInstrumentationProvider,
    MockListeningHistoryProvider,
)
from palette_api.schemas import (
    ApiError,
    ImageCredit,
    ImageVariant,
    ImageTone,
    InstrumentImage,
    InstrumentResource,
    PaletteReport,
)


NO_STORE_HEADERS = {"Cache-Control": "no-store"}
CATALOG_STATS_CACHE_CONTROL = "public, max-age=300, s-maxage=300"
# Editorial D1 publications become visible without requiring a zone-wide purge.
INSTRUMENT_CACHE_CONTROL = "public, max-age=300, s-maxage=300"
PALETTE_CACHE_CONTROL = "public, max-age=300, s-maxage=300"


app = FastAPI(
    title="Timbre Palette API",
    summary="Retratos instrumentais de históricos públicos do Last.fm.",
    version="0.3.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept"],
)


@app.get("/v1/catalog/stats", operation_id="getCatalogStats")
async def get_catalog_stats(request: Request) -> JSONResponse:
    environment = request.scope.get("env")
    db = (environment.get("DB") if isinstance(environment, Mapping)
          else getattr(environment, "DB", None))
    if db is None:
        return JSONResponse({"recordings_with_evidence": 0},
                            headers=NO_STORE_HEADERS)
    row = await db.prepare("""
        SELECT COUNT(DISTINCT ic.recording_id) AS recordings_with_evidence
        FROM instrument_claims AS ic
        LEFT JOIN instruments AS i ON i.slug = ic.instrument_slug
        JOIN instrument_families AS f
          ON f.slug = COALESCE(i.family_slug, ic.family_slug)
        WHERE ic.confidence_level IN ('documented', 'editorially_verified')
          AND EXISTS (
              SELECT 1 FROM evidence_items AS ei
              WHERE ei.claim_id = ic.id AND ei.scope IN ('recording', 'track')
          )
    """).first()
    return JSONResponse(
        {"recordings_with_evidence": int(_get_val(row, "recordings_with_evidence", 0))},
        headers={"Cache-Control": CATALOG_STATS_CACHE_CONTROL},
    )


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


async def get_image_catalog(request: Request) -> InstrumentImageCatalog:
    environment = request.scope.get("env")
    base_url = (
        environment.get("IMAGE_ASSET_BASE_URL")
        if isinstance(environment, Mapping)
        else getattr(environment, "IMAGE_ASSET_BASE_URL", None)
    )
    if not isinstance(base_url, str) or not base_url.strip():
        return DEFAULT_IMAGE_CATALOG
    try:
        return DEFAULT_IMAGE_CATALOG.with_base_url(base_url.strip())
    except ValueError as error:
        raise ApiProblem(503, "image_assets_not_configured", str(error)) from error


async def get_palette_service(
    request: Request,
    image_catalog: Annotated[InstrumentImageCatalog, Depends(get_image_catalog)],
) -> PaletteService:
    environment = request.scope.get("env")
    if isinstance(environment, Mapping):
        api_key = environment.get("LASTFM_API_KEY")
        db = environment.get("DB")
        queue = environment.get("ENRICHMENT_QUEUE")
    else:
        api_key = getattr(environment, "LASTFM_API_KEY", None)
        db = getattr(environment, "DB", None)
        queue = getattr(environment, "ENRICHMENT_QUEUE", None)

    mode = (
        environment.get("PALETTE_API_MODE")
        if isinstance(environment, Mapping)
        else getattr(environment, "PALETTE_API_MODE", None)
    )
    if mode == "mock":
        return PaletteService(
            history_provider=MockListeningHistoryProvider(),
            instrumentation_provider=MockInstrumentationProvider(),
            image_catalog=image_catalog,
        )

    if not isinstance(api_key, str) or not api_key.strip():
        raise LastFmConfigurationError("LASTFM_API_KEY was not configured.")

    instrumentation_provider = (
        D1InstrumentationProvider(db)
        if db is not None
        else MockInstrumentationProvider()
    )
    enrichment_scheduler = (
        D1QueueEnrichmentScheduler(db, queue)
        if db is not None and queue is not None
        else None
    )
    return PaletteService(
        history_provider=LastFmListeningHistoryProvider(
            api_key=api_key,
            transport=WorkersFetchJsonTransport(),
        ),
        instrumentation_provider=instrumentation_provider,
        enrichment_scheduler=enrichment_scheduler,
        image_catalog=image_catalog,
    )


async def get_instrument_catalog(request: Request) -> InstrumentCatalogProvider:
    environment = request.scope.get("env")
    if isinstance(environment, Mapping):
        db = environment.get("DB")
    else:
        db = getattr(environment, "DB", None)

    mode = (
        environment.get("PALETTE_API_MODE")
        if isinstance(environment, Mapping)
        else getattr(environment, "PALETTE_API_MODE", None)
    )
    if mode == "mock":
        return MockInstrumentCatalog()

    if db is not None:
        return D1InstrumentCatalog(db)
    return MockInstrumentCatalog()


@app.exception_handler(ApiProblem)
async def handle_api_problem(_request: Request, error: ApiProblem) -> JSONResponse:
    response = ApiError(code=error.code, message=error.message)
    return JSONResponse(
        status_code=error.status_code,
        content=response.model_dump(),
        headers=NO_STORE_HEADERS,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request,
    _error: RequestValidationError,
) -> JSONResponse:
    response = ApiError(
        code="invalid_request",
        message="The request parameters are invalid.",
    )
    return JSONResponse(status_code=422, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.exception_handler(LastFmConfigurationError)
async def handle_lastfm_configuration_error(
    request: Request,
    error: LastFmConfigurationError,
) -> JSONResponse:
    _log_upstream_error(request, error)
    response = ApiError(
        code="lastfm_not_configured",
        message="The Last.fm integration is not configured correctly.",
    )
    return JSONResponse(status_code=503, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.exception_handler(LastFmProfileNotFoundError)
async def handle_lastfm_profile_not_found(
    _request: Request,
    _error: LastFmProfileNotFoundError,
) -> JSONResponse:
    response = ApiError(
        code="lastfm_profile_not_found",
        message="The specified profile was not found on Last.fm.",
    )
    return JSONResponse(status_code=404, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.exception_handler(LastFmRateLimitError)
async def handle_lastfm_rate_limit(
    request: Request,
    error: LastFmRateLimitError,
) -> JSONResponse:
    _log_upstream_error(request, error)
    response = ApiError(
        code="lastfm_rate_limited",
        message="Last.fm has temporarily rate-limited project requests.",
    )
    return JSONResponse(
        status_code=503,
        content=response.model_dump(),
        headers={**NO_STORE_HEADERS, "Retry-After": "60"},
    )


@app.exception_handler(LastFmUnavailableError)
@app.exception_handler(LastFmInvalidResponseError)
async def handle_lastfm_upstream_error(
    request: Request,
    error: LastFmUnavailableError | LastFmInvalidResponseError,
) -> JSONResponse:
    _log_upstream_error(request, error)
    response = ApiError(
        code="lastfm_unavailable",
        message="Could not retrieve listening history from Last.fm.",
    )
    return JSONResponse(status_code=502, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.exception_handler(EmptyListeningHistoryError)
async def handle_empty_history(
    request: Request,
    error: EmptyListeningHistoryError,
) -> JSONResponse:
    username = str(error) or "unknown"
    print(
        json.dumps(
            {
                "event": "empty_listening_history",
                "path": request.url.path,
                "username": username,
            }
        )
    )
    response = ApiError(
        code="empty_listening_history",
        message="There is not enough listening history to produce a palette.",
    )
    return JSONResponse(status_code=422, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    print(
        json.dumps(
            {
                "event": "unhandled_error",
                "path": request.url.path,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    )
    response = ApiError(
        code="internal_error",
        message="Could not complete the request.",
    )
    return JSONResponse(status_code=500, content=response.model_dump(), headers=NO_STORE_HEADERS)


@app.get(
    "/v1/profiles/{username}/palette",
    operation_id="getProfilePalette",
    response_model=PaletteReport,
    responses={
        404: {"model": ApiError},
        422: {"model": ApiError},
        502: {"model": ApiError},
        503: {"model": ApiError},
    },
)
async def get_profile_palette(
    username: Annotated[str, Path(min_length=1, max_length=64)],
    palette_service: Annotated[PaletteService, Depends(get_palette_service)],
    response: Response,
    period: Annotated[
        ListeningPeriod,
        Query(description="Período do histórico a considerar."),
    ] = ListeningPeriod.SEVEN_DAYS,
) -> PaletteReport | JSONResponse:
    normalized_username = username.strip()
    if not normalized_username:
        raise ApiProblem(
            status_code=422,
            code="invalid_username",
            message="The profile must contain at least one visible character.",
        )

    report = await palette_service.analyze(normalized_username, period)
    response.headers["Cache-Control"] = PALETTE_CACHE_CONTROL
    return report


@app.get(
    "/v1/instruments/{slug}",
    operation_id="getInstrument",
    response_model=InstrumentResource,
    responses={404: {"model": ApiError}},
)
async def get_instrument(
    slug: Annotated[str, Path(min_length=1, max_length=80)],
    catalog: Annotated[InstrumentCatalogProvider, Depends(get_instrument_catalog)],
    image_catalog: Annotated[InstrumentImageCatalog, Depends(get_image_catalog)],
    response: Response,
) -> InstrumentResource:
    resource = await catalog.get(slug.strip().lower())
    if resource is None:
        raise ApiProblem(
            status_code=404,
            code="instrument_not_found",
            message="Instrument or sound family not found.",
        )

    family_slug = resource.family_slug if resource.kind == "instrument" else resource.slug
    tone = image_catalog.family_tone(family_slug) if family_slug else None
    resource = resource.model_copy(update={
        "tone": ImageTone(**tone) if tone else None,
        "image_catalog_version": image_catalog.version,
    })
    resolved = image_catalog.resolve(
        resource.slug,
        resource.family_slug if resource.kind == "instrument" else resource.slug,
    )
    if resolved is None:
        response.headers["Cache-Control"] = INSTRUMENT_CACHE_CONTROL
        return resource
    image = InstrumentImage(
        asset_id=resolved.asset_id,
        resolution=resolved.resolution,
        depicted_instrument_slug=resolved.depicted_instrument_slug,
        alt=resolved.alt,
        caption=resolved.caption,
        variants=[ImageVariant(name="detail", url=resolved.url, width=resolved.width, height=resolved.height)],
        tone=ImageTone(shadow=resolved.shadow, highlight=resolved.highlight),
        credit=ImageCredit(
            **{key: resolved.credit.get(key) for key in ImageCredit.model_fields}
        ),
    )
    response.headers["Cache-Control"] = INSTRUMENT_CACHE_CONTROL
    return resource.model_copy(
        update={"image": image, "image_catalog_version": image_catalog.version}
    )


def _log_upstream_error(request: Request, error: Exception) -> None:
    print(
        json.dumps(
            {
                "event": "lastfm_error",
                "path": request.url.path,
                "error_type": type(error).__name__,
            }
        )
    )
