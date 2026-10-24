/** Session start times come from the log file name, as "YYYY-MM-DDTHH:MM:SS". */

type Dated = { started_at: string | null };

/** True when the logs were recorded on more than one day, so a clock time alone is ambiguous. */
export function spansDays(logs: Dated[]): boolean {
  return new Set(logs.map((l) => l.started_at?.slice(0, 10)).filter(Boolean)).size > 1;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "19 Nov 11:42:03" when dates matter, otherwise "11:42:03". */
export function stamp(iso: string, withDate: boolean): string {
  const time = iso.slice(11, 19);
  if (!withDate) return time;
  return `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1] ?? ""} ${time}`;
}

/** "Wed 19 Nov 2025" */
export function dayLabel(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
