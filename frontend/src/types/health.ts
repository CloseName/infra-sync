export type HealthStatus = 'healthy' | 'degraded' | 'unavailable' | 'unknown';
export type ComponentName = 'api' | 'application' | 'database' | 'registry' | 'netbox';

export interface ComponentHealth {
  status: HealthStatus;
  message: string;
  error_code: string | null;
}

export interface SystemHealth {
  status: HealthStatus;
  components: Record<ComponentName, ComponentHealth>;
}
