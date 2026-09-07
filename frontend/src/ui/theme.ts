export type ThemePreference = "light" | "dark" | "system";
export const themeKey = "netbox-sync.theme";
export function themePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}
export function readTheme(): ThemePreference {
  try {
    return themePreference(localStorage.getItem(themeKey));
  } catch {
    return "system";
  }
}
export function applyTheme(preference: ThemePreference) {
  document.documentElement.dataset.theme =
    preference === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : preference;
}
