"""Read-only FastAPI factory and transport boundaries."""

import json
import logging
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from ..application.health import SystemHealthService
from ..application.sources import SourceReadError, SourceVisibilityService
from ..application.sources import source_view
from ..application.onboarding import EphemeralOnboardingStore, OnboardingError, SourceOnboardingService
from .database import PostgresHealthProbe
from .dto import ErrorDTO, ErrorDetailDTO, LivenessDTO, SystemHealthDTO, VersionDTO
from .settings import ApiSettings, application_version
from .source_reader import PostgresSourceReader
from .dto import DiscoveryResultDTO, SourceDTO, SourceListDTO
from .discovery_client import DiscoveryRequestError, DiscoveryWorkerClient
from .onboarding_dto import ConnectionRequest, ConnectionResult, RegistrationRequest
from .onboarding_dto import CancellationRequest, CancellationResult
from .onboarding_adapters import BrokerSecretStore, RegistrationRegistry, test_esxi, test_proxmox

LOGGER = logging.getLogger('infra_sync.api')


def _error(request, status, code, message):
    request.state.error_code = code
    dto = ErrorDTO(error=ErrorDetailDTO(code=code, message=message, request_id=request.state.request_id))
    return JSONResponse(status_code=status, content=dto.model_dump(mode='json'))


def _install_boundaries(app, settings):
    @app.exception_handler(OnboardingError)
    async def onboarding_error(request, exc):
        errors = {
            'SOURCE_ALREADY_EXISTS': (409, 'Source already exists'),
            'SOURCE_UNSUPPORTED': (422, 'Source type is unsupported'),
            'SOURCE_AUTH_FAILED': (422, 'Source authentication failed'),
            'SOURCE_TLS_FAILED': (422, 'Source TLS verification failed'),
            'SOURCE_TIMEOUT': (504, 'Source connection timed out'),
            'SOURCE_DESTINATION_DENIED': (422, 'Source destination is not permitted'),
            'SOURCE_CONNECTION_FAILED': (502, 'Source connection failed'),
            'ONBOARDING_TOKEN_INVALID': (409, 'Onboarding expired or already consumed; test again'),
            'SECRET_STORE_FAILED': (503, 'Protected secret storage is unavailable'),
            'REGISTRATION_UNAVAILABLE': (503, 'Registration is unavailable'),
            'REGISTRATION_FAILED': (503, 'Source registration failed'),
            'REGISTRATION_UNCERTAIN': (503, 'Registration outcome requires operator reconciliation'),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(SourceReadError)
    async def source_error(request, exc):
        errors = {
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_DATA_INVALID': (503, 'Source metadata is unavailable'),
            'REGISTRY_UNAVAILABLE': (503, 'Source registry is unavailable'),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(DiscoveryRequestError)
    async def discovery_error(request, exc):
        errors = {
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_DISABLED': (409, 'Disabled sources cannot be discovered'),
            'CREDENTIAL_UNAVAILABLE': (503, 'Discovery credentials are unavailable'),
            'REGISTRY_UNAVAILABLE': (503, 'Discovery registry is unavailable'),
            'DISCOVERY_TIMEOUT': (504, 'Discovery timed out'),
            'PROVIDER_UNAVAILABLE': (502, 'Source discovery failed'),
            'NETBOX_UNAVAILABLE': (502, 'NetBox comparison failed'),
            'DISCOVERY_FAILED': (502, 'Discovery failed'),
            'DISCOVERY_RESPONSE_INVALID': (502, 'Discovery returned an invalid response'),
            'DISCOVERY_UNAVAILABLE': (503, 'Discovery worker is unavailable'),
        }
        status, message = errors.get(exc.code, errors['DISCOVERY_UNAVAILABLE'])
        return _error(request, status, exc.code, message)

    @app.middleware('http')
    async def request_boundary(request: Request, call_next):
        # Never trust/re-emit client correlation headers, URLs, query or body.
        request.state.request_id = str(uuid4())
        request.state.error_code = None
        try:
            if request.method == 'POST' and (
                    request.url.path in (
                        '/api/v1/sources', '/api/v1/sources/test-connection',
                        '/api/v1/sources/cancel-onboarding',
                    ) or (
                        request.url.path.startswith('/api/v1/sources/')
                        and request.url.path.endswith('/discovery')
                    )):
                origin = urlsplit(request.headers.get('origin', ''))
                host = request.headers.get('host', '')
                if (host not in settings.allowed_write_hosts or origin.netloc != host
                        or origin.scheme != request.url.scheme or origin.path not in ('', '/')
                        or origin.query or origin.fragment or origin.username is not None
                        or request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none')
                        or request.headers.get('x-infra-sync-csrf') != 'same-origin'
                        or request.headers.get('content-type', '').split(';')[0] != 'application/json'):
                    response = _error(request, 403, 'API_WRITE_FORBIDDEN', 'Same-origin write protection failed')
                elif (not request.headers.get('content-length', '').isdigit()
                      or int(request.headers['content-length']) > 16384):
                    response = _error(request, 413, 'API_REQUEST_TOO_LARGE', 'Request body is too large')
                else:
                    response = await call_next(request)
            else:
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


def create_app(settings=None, service=None, source_service=None, onboarding_service=None,
               discovery_client=None):
    """Construct without DB access; all environment reading is confined to bootstrap."""
    if not LOGGER.handlers:
        LOGGER.addHandler(logging.StreamHandler())
    LOGGER.setLevel(logging.INFO)
    settings = settings or ApiSettings.from_environment()
    service = service or SystemHealthService(
        PostgresHealthProbe(settings), netbox_configured=settings.netbox_configured,
    )
    source_service = source_service or SourceVisibilityService(PostgresSourceReader(settings))
    onboarding_service = onboarding_service or SourceOnboardingService(
        {'proxmox': partial(test_proxmox, policy=settings.egress_policy),
         'esxi': partial(test_esxi, policy=settings.egress_policy)}, EphemeralOnboardingStore(),
        RegistrationRegistry(settings.registration_dsn, settings.registry_schema),
        BrokerSecretStore(settings.broker_socket),
    )
    discovery_client = discovery_client or DiscoveryWorkerClient(settings.discovery_socket)
    app = FastAPI(title='Infra Sync', version=application_version(),
                  docs_url=None, redoc_url=None, openapi_url=None, debug=False)
    _install_boundaries(app, settings)
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

    @router.get('/sources', response_model=SourceListDTO)
    def sources():
        return SourceListDTO(sources=[SourceDTO.from_view(view) for view in source_service.list_sources()])

    @router.get('/sources/{source_instance}', response_model=SourceDTO)
    def source_detail(source_instance: str):
        return SourceDTO.from_view(source_service.get_source(source_instance))

    @router.post('/sources/{source_instance}/discovery', response_model=DiscoveryResultDTO)
    def discover_source(source_instance: str):
        result = DiscoveryResultDTO.from_worker(discovery_client.discover(source_instance))
        if result.source_instance != source_instance:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        return result

    @router.post('/sources/test-connection', response_model=ConnectionResult)
    def connection_test(request: ConnectionRequest):
        token = onboarding_service.test_connection(request.credentials())
        return ConnectionResult(onboarding_token=token)

    @router.post('/sources', response_model=SourceDTO, status_code=201)
    def register_source(request: RegistrationRequest):
        onboarding_service.register(request.command())
        return SourceDTO.from_view(source_view({
            **request.model_dump(), 'enabled': True, 'sync_enabled': False, 'legacy_identity_owner': False,
        }))

    @router.post('/sources/cancel-onboarding', response_model=CancellationResult)
    def cancel_onboarding(request: CancellationRequest):
        onboarding_service.cancel(request.onboarding_token)
        return CancellationResult()

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
