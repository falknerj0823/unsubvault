import { useQuery } from "@tanstack/react-query";
import { getAppSettings } from "./api";

/** The timezone chosen in Settings (IANA name); "" means use the browser's. */
export function useTimezone(): string {
  const { data } = useQuery({ queryKey: ["app-settings"], queryFn: getAppSettings });
  return data?.timezone ?? "";
}

export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Format a UTC ISO string (…Z) in the chosen timezone. Falls back to the browser's if the name is invalid. */
export function formatTime(iso: string | null | undefined, tz: string, style: "full" | "short" = "full"): string {
  if (!iso) return "—";
  const opts: Intl.DateTimeFormatOptions = style === "full"
    ? { dateStyle: "medium", timeStyle: "medium" } : { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" };
  try { return new Intl.DateTimeFormat(undefined, { ...opts, timeZone: tz || undefined }).format(new Date(iso)); }
  catch { return new Intl.DateTimeFormat(undefined, opts).format(new Date(iso)); }
}

export function duration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "";
  const s = Math.max(0, Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function timezoneList(): string[] {
  const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
  return fn ? fn("timeZone") : ["UTC", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney"];
}
