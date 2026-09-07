import type { SyncPlanItem, SyncAction } from "../api/sync.ts";
import type { Status } from "./status.ts";
export const actionLabels: Record<SyncAction, string> = {
  CREATE: "Create",
  UPDATE: "Update",
  NO_CHANGE: "Unchanged",
  REVIEW_REQUIRED: "Needs review",
  BLOCKED: "Blocked",
  IGNORED: "Ignored",
  UNSUPPORTED: "Unsupported",
  RETAIN_ONLY: "Retained",
};
export function actionStatus(action: SyncAction): Status {
  return {
    label: actionLabels[action],
    tone:
      action === "BLOCKED"
        ? "danger"
        : action === "REVIEW_REQUIRED"
          ? "warning"
          : action === "CREATE" || action === "UPDATE"
            ? "info"
            : "neutral",
    icon:
      action === "BLOCKED" || action === "REVIEW_REQUIRED"
        ? "!"
        : action === "CREATE"
          ? "+"
          : action === "UPDATE"
            ? "↻"
            : "−",
  };
}
export const policyRow = (item: SyncPlanItem) =>
  item.action === "RETAIN_ONLY" && item.object_kind === "source";
export function planCounts(items: SyncPlanItem[]) {
  const result: Record<SyncAction, number> = {
    CREATE: 0,
    UPDATE: 0,
    NO_CHANGE: 0,
    REVIEW_REQUIRED: 0,
    BLOCKED: 0,
    IGNORED: 0,
    UNSUPPORTED: 0,
    RETAIN_ONLY: 0,
  };
  for (const item of items) if (!policyRow(item)) result[item.action]++;
  return result;
}
export const countLabels: Record<SyncAction, string> = {
  CREATE: "Create operations",
  UPDATE: "Update operations",
  REVIEW_REQUIRED: "Needs review rows",
  BLOCKED: "Blocking rows",
  NO_CHANGE: "Unchanged rows",
  RETAIN_ONLY: "Retained rows",
  IGNORED: "Ignored rows",
  UNSUPPORTED: "Unsupported rows",
};
export type PlanView = "Changes" | "Attention" | "All";
export function filterPlan(
  items: SyncPlanItem[],
  view: PlanView,
  action: string,
  kind: string,
  search: string,
) {
  const query = search.toLocaleLowerCase().trim();
  return items.filter(
    (item) =>
      !policyRow(item) &&
      (view === "All" ||
        (view === "Changes"
          ? ["CREATE", "UPDATE"]
          : ["REVIEW_REQUIRED", "BLOCKED"]
        ).includes(item.action)) &&
      (!action || item.action === action) &&
      (!kind || item.object_kind === kind) &&
      (!query ||
        [item.name, item.object_kind, item.reason, item.external_id].some(
          (value) => value.toLocaleLowerCase().includes(query),
        )),
  );
}
export interface FieldValue {
  provided: boolean;
  value?: unknown;
}
export function managedFields(item: SyncPlanItem) {
  const before = new Map(item.before as [string, unknown][]),
    after = new Map(item.after as [string, unknown][]);
  return [...new Set([...before.keys(), ...after.keys()])].map((field) => ({
    field,
    before: {
      provided: before.has(field),
      value: before.get(field),
    } as FieldValue,
    after: {
      provided: after.has(field),
      value: after.get(field),
    } as FieldValue,
  }));
}
export function fieldText(field: FieldValue): string {
  if (!field.provided) return "Not provided";
  if (field.value === null) return "null";
  if (field.value === "") return '"" (empty string)';
  return typeof field.value === "string"
    ? field.value
    : JSON.stringify(field.value);
}
export function kindLabel(kind: string) {
  const labels: Record<string, string> = {
    host: "Host",
    qemu: "Virtual machine",
    vm: "Virtual machine",
    lxc: "Container",
    "virtualization.virtual_machines": "Virtual machine",
    "dcim.devices": "Device",
    "ipam.ip_addresses": "IP address",
    "virtualization.interfaces": "VM interface",
    "dcim.interfaces": "Device interface",
    source: "Source policy",
  };
  return labels[kind] ?? kind;
}
