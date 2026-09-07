import type { Resource } from "./useResource";
import { Alert, LoadingState, Timestamp } from "./primitives";
export function ResourceFeedback<T>({
  resource,
  label,
  table = false,
  evidenceAt,
}: {
  resource: Resource<T> & { refresh: () => void };
  label: string;
  table?: boolean;
  evidenceAt?: string;
}) {
  return (
    <>
      {resource.loading && !resource.data && (
        <LoadingState label={`Loading ${label}...`} table={table} />
      )}
      {resource.loading && resource.data && (
        <p role="status">Refreshing {label}…</p>
      )}
      {resource.error && (
        <Alert retry={resource.refresh}>
          {resource.data ? (
            <>
              Could not refresh. Showing data from{" "}
              <Timestamp value={evidenceAt ?? resource.received} />.
            </>
          ) : (
            <>{label[0].toUpperCase() + label.slice(1)} could not be loaded.</>
          )}
        </Alert>
      )}
    </>
  );
}
