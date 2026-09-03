"""Read-only FastAPI factory and transport boundaries."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from ..application.health import SystemHealthService
from .database import PostgresHealthProbe
from .dto import ErrorDTO, ErrorDetailDTO, LivenessDTO, SystemHealthDTO, VersionDTO
from .settings import ApiSettings, application_version

LOGGER = logging.getLogger('infra_sync.api')


def _error(request, status, code, message):
    request.state.error_code = code
    dto = ErrorDTO(error=ErrorDetailDTO(code=code, message=message, request_id=request.state.request_id))
    return JSONResponse(status_code=status, content=dto.model_dump(mode='json'))


def _install_boundaries(app):
    @app.middleware('http')
    async def request_boundary(request: Request, call_next):
        # Never trust/re-emit client correlation headers, URLs, query or body.
        request.state.request_id = str(uuid4())
        request.state.error_code = None
        try:
            response = await call_next(request)
        except Exception:  # pylint: disable=broad-exception-caught
            response = _error(request, 500, 'API_INTERNAL_ERROR', 'API request failed')
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        LOGGER.log(logging.ERROR if response.status_code >= 500 else logging.INFO, json.dumps({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': 'ERROR' if response.status_code >= 500 else 'INFO',
            'component': 'api',
            'request_id': request.state.request_id,
            'run_id': None,
            'source_instance': None,
            'error_code': request.state.error_code,
            'message': 'HTTP request completed',
            'status_code': response.status_code,
        }))
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        codes = {404: ('API_NOT_FOUND', 'Endpoint not found'),
                 405: ('API_METHOD_NOT_ALLOWED', 'Method not allowed')}
        code, message = codes.get(exc.status_code, ('API_REQUEST_FAILED', 'Request rejected'))
        return _error(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        return _error(request, 422, 'API_VALIDATION_FAILED', 'Request validation failed')


def create_app(settings=None, service=None):
    """Construct without DB access; all environment reading is confined to bootstrap."""
    if not LOGGER.handlers:
        LOGGER.addHandler(logging.StreamHandler())
    LOGGER.setLevel(logging.INFO)
    settings = settings or ApiSettings.from_environment()
    service = service or SystemHealthService(
        PostgresHealthProbe(settings), netbox_configured=settings.netbox_configured,
    )
    app = FastAPI(title='Infra Sync', version=application_version(),
                  docs_url=None, redoc_url=None, openapi_url=None, debug=False)
    _install_boundaries(app)
    router = APIRouter(prefix='/api/v1')

    @router.get('/health', response_model=LivenessDTO)
    def health():
        return LivenessDTO()

    @router.get('/system/health', response_model=SystemHealthDTO)
    def system_health():
        return SystemHealthDTO.from_result(service.check())

    @router.get('/version', response_model=VersionDTO)
    def version():
        return VersionDTO(version=application_version())

    app.include_router(router)
    if settings.web_dist:
        root = Path(settings.web_dist)
        if not (root / 'index.html').is_file() or not (root / 'assets').is_dir():
            raise ValueError('Frontend build is unavailable')
        app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')

        @app.get('/', include_in_schema=False)
        def frontend():
            return FileResponse(root / 'index.html')

    return app
