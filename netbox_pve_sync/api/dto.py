"""Explicit public DTOs; no ORM/configuration objects are exposed."""

from pydantic import BaseModel, ConfigDict

from ..application.health import HealthStatus
from ..application.observability import ErrorCode


class PublicModel(BaseModel):
    """Disallow accidental extra response fields."""

    model_config = ConfigDict(extra='forbid', frozen=True)


class ComponentHealthDTO(PublicModel):
    """Safe component status."""

    status: HealthStatus
    message: str
    error_code: ErrorCode | None = None


class ComponentsDTO(PublicModel):
    """Explicitly enumerated system components."""

    api: ComponentHealthDTO
    application: ComponentHealthDTO
    database: ComponentHealthDTO
    registry: ComponentHealthDTO
    netbox: ComponentHealthDTO


class SystemHealthDTO(PublicModel):
    """Read-only snapshot, not a synchronization outcome."""

    status: HealthStatus
    components: ComponentsDTO

    @classmethod
    def from_result(cls, result):
        """Map only allowlisted domain fields."""
        components = {}
        for name in ('api', 'application', 'database', 'registry', 'netbox'):
            component = getattr(result, name)
            components[name] = ComponentHealthDTO(
                status=component.status, message=component.message, error_code=component.error_code,
            )
        return cls(status=result.status, components=ComponentsDTO(**components))


class LivenessDTO(PublicModel):
    """Cheap process liveness; no database access."""

    status: HealthStatus = HealthStatus.HEALTHY


class VersionDTO(PublicModel):
    """Package metadata, independent of Git."""

    name: str = 'Infra Sync'
    version: str


class ErrorDetailDTO(PublicModel):
    """Stable error envelope with server-generated correlation."""

    code: str
    message: str
    request_id: str


class ErrorDTO(PublicModel):
    """Never includes exception details, request input or internal configuration."""

    error: ErrorDetailDTO
