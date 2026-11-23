const number = new Intl.NumberFormat("en-US");
const date = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
const dateTime = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });
const shortDay = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export function formatNumber(value: number): string {
  return number.format(value);
}

export function formatDate(value: string): string {
  return date.format(new Date(value));
}

export function formatDateTime(value: string | null): string {
  return value ? dateTime.format(new Date(value)) : "None";
}

// A UTC day as "YYYY-MM-DD" to "Nov 2".
export function formatShortDay(day: string): string {
  return shortDay.format(new Date(`${day}T00:00:00Z`));
}
