"""Explicit public DTOs; no ORM/configuration objects are exposed."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class SourceDTO(PublicModel):
    """Explicit source projection; list and detail share the same safe fields."""

    source_instance: str
    type: Literal['proxmox', 'esxi']
    name: str
    address: str
    enabled: bool
    sync_enabled: bool
    verify_ssl: bool
    sync_interval_seconds: int
    site_slug: str
    cluster_name: str
    platform_slug: str
    device_role_slug: str
    device_type_slug: str
    cluster_type_slug: str
    legacy_identity_owner: bool
    status: Literal['enabled', 'disabled', 'sync_disabled']

    @classmethod
    def from_view(cls, view):
        """Copy only named DTO fields, never serialize arbitrary internal state."""
        return cls(
            source_instance=view.source_instance, type=view.type, name=view.name, address=view.address,
            enabled=view.enabled, sync_enabled=view.sync_enabled, verify_ssl=view.verify_ssl,
            sync_interval_seconds=view.sync_interval_seconds, site_slug=view.site_slug,
            cluster_name=view.cluster_name, platform_slug=view.platform_slug,
            device_role_slug=view.device_role_slug, device_type_slug=view.device_type_slug,
            cluster_type_slug=view.cluster_type_slug, legacy_identity_owner=view.legacy_identity_owner,
            status=view.status,
        )


class SourceListDTO(PublicModel):
    """Stable list envelope including an empty registry."""

    sources: list[SourceDTO]


class DiscoveryItemDTO(PublicModel):
    object_kind: Literal['host', 'qemu', 'lxc', 'vm']
    name: str
    external_id: str
    classification: Literal['MANAGED', 'REVIEW_REQUIRED', 'WOULD_CREATE', 'IGNORED',
                            'UNSUPPORTED', 'CONFLICT', 'NO_CHANGE']
    reason_code: str
    reason: str
    future_action: Literal['none', 'create', 'update', 'review', 'ignored', 'unsupported']
    matched_object_id: int | str | None = None
    matched_object_name: str | None = None


class DiscoveryResultDTO(PublicModel):
    source_instance: str
    source_type: Literal['proxmox', 'esxi']
    site_slug: str
    cluster_name: str
    items: list[DiscoveryItemDTO]

    @classmethod
    def from_worker(cls, value):
        """Validate every allowlisted worker field before public serialization."""
        return cls.model_validate(value)


class SyncPlanItemDTO(PublicModel):
    """Exact allowlisted action in a canonical sync plan."""

    object_kind: str
    external_id: str
    name: str
    action: Literal['CREATE', 'UPDATE', 'NO_CHANGE', 'REVIEW_REQUIRED', 'BLOCKED',
                    'IGNORED', 'UNSUPPORTED', 'RETAIN_ONLY']
    reason_code: str
    reason: str
    matched_object_id: int | str | None = None
    before: list[list[object]]
    after: list[list[object]]


class SyncPlanDTO(PublicModel):
    """Secret-free plan returned by the read-only worker."""

    source_instance: str
    source_type: Literal['proxmox', 'esxi']
    source_fingerprint: str
    target_fingerprint: str
    provider_fingerprint: str
    netbox_fingerprint: str
    schema_version: int
    planner_version: str
    items: list[SyncPlanItemDTO]
    apply_allowed: bool
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @classmethod
    def from_worker(cls, value):
        """Exclude the internal registry ID while retaining its binding inside the digest."""
        if not isinstance(value, dict):
            return cls.model_validate(value)
        return cls.model_validate({key: item for key, item in value.items() if key != 'source_id'})


class SyncPlanRequestDTO(PublicModel):
    """An intentionally empty request: the browser cannot select scope or operations."""


class ConfirmationRequestDTO(PublicModel):
    """The browser may identify an exact plan but cannot submit operations."""

    plan_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: Literal[True]


class ConfirmationDTO(PublicModel):
    """Short-lived opaque capability; its value is never logged."""

    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_in_seconds: int = 300


class ApplyRequestDTO(PublicModel):
    """Only a worker-issued capability crosses the API boundary."""

    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')


class ApplyResultDTO(PublicModel):
    """Explicit non-transactional synchronization result."""

    status: Literal['SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN']
    plan_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
