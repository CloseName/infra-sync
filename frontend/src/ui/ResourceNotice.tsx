import type { Resource } from "./useResource";
import { Alert, Timestamp } from "./primitives";
export function ResourceNotice({
  resource,
  name,
  retry,
}: {
  resource: Resource<unknown>;
  name: string;
  retry: () => void;
}) {
  return resource.error ? (
    <Alert retry={retry}>
      {resource.data ? (
        <>
          Could not refresh {name}. Showing data from{" "}
          <Timestamp value={resource.received} />.
        </>
      ) : (
        <>{name} unavailable. This section could not be loaded.</>
      )}
    </Alert>
  ) : null;
}
