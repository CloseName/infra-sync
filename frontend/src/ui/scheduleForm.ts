export const schedulePresets = [300, 600, 900, 1800, 3600, 7200, 21600];
export type TimeUnit = "seconds" | "minutes" | "hours";
export interface IntervalDraft {
  preset: string;
  amount: string;
  unit: TimeUnit;
}
const scales = { seconds: 1, minutes: 60, hours: 3600 };
export function intervalDraft(seconds: number): IntervalDraft {
  const unit =
    seconds % 3600 === 0 ? "hours" : seconds % 60 === 0 ? "minutes" : "seconds";
  return {
    preset: schedulePresets.includes(seconds) ? String(seconds) : "custom",
    amount: String(seconds / scales[unit]),
    unit,
  };
}
export function intervalSeconds(draft: IntervalDraft): number | null {
  // Accept exact integer seconds after conversion; never round a user's value.
  const input = draft.preset === "custom" ? draft.amount.trim() : draft.preset;
  if (!/^\d+(?:\.\d+)?$/.test(input)) return null;
  if (input.length > 32) return null;
  const [whole, fraction = ""] = input.split(".");
  const denominator = 10n ** BigInt(fraction.length);
  const numerator =
    BigInt(whole + fraction) *
    BigInt(draft.preset === "custom" ? scales[draft.unit] : 1);
  if (numerator % denominator !== 0n) return null;
  const seconds = Number(numerator / denominator);
  return Number.isSafeInteger(seconds) && seconds >= 60 && seconds <= 86400
    ? seconds
    : null;
}
