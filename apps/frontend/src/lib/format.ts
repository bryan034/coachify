/** One way to write dates and durations everywhere: "Tue, 4 May 2027" and "10 hours". */

const toDate = (value: string | Date) => value instanceof Date ? value : /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00Z`) : new Date(value);
const dateOnly = (value: string | Date) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);

/** Each field is formatted on its own, so the output never depends on a locale's punctuation. */
function parts(value: string | Date, options: Intl.DateTimeFormatOptions) {
 const date = toDate(value);
 if (Number.isNaN(date.getTime())) return null;
 const zone = dateOnly(value) ? { timeZone: 'UTC' } : {};
 const field = (option: Intl.DateTimeFormatOptions) => date.toLocaleDateString('en-GB', { ...option, ...zone });
 return {
  weekday: options.weekday ? field({ weekday: options.weekday }) : '',
  day: field({ day: 'numeric' }), month: field({ month: 'short' }), year: field({ year: 'numeric' }),
 };
}

/** "Tue, 4 May 2027". Date-only strings are read as that calendar day wherever the viewer is. */
export function formatDate(value: string | Date): string {
 const p = parts(value, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
 return p ? `${p.weekday}, ${p.day} ${p.month} ${p.year}` : String(value);
}

/** "4 May 2027", for places without room for the weekday. */
export function formatDayMonthYear(value: string | Date): string {
 const p = parts(value, { day: 'numeric', month: 'short', year: 'numeric' });
 return p ? `${p.day} ${p.month} ${p.year}` : String(value);
}

/** "Tue, 4 May 2027, 7:30 pm" for timestamps. */
export function formatDateTime(value: string | Date): string {
 const date = toDate(value);
 if (Number.isNaN(date.getTime())) return String(value);
 const hours = date.getHours(), minutes = String(date.getMinutes()).padStart(2, '0');
 const time = `${hours % 12 || 12}:${minutes} ${hours < 12 ? 'am' : 'pm'}`;
 return `${formatDate(date)}, ${time}`;
}

const unit = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

/** 600 → "10 hours", 90 → "1 hour 30 minutes", 45 → "45 minutes". Rounds to whole minutes. */
export function formatDuration(minutes: number): string {
 if (!Number.isFinite(minutes)) return '';
 const total = Math.max(0, Math.round(minutes));
 const hours = Math.floor(total / 60), rest = total % 60;
 if (!hours) return unit(rest, 'minute');
 return rest ? `${unit(hours, 'hour')} ${unit(rest, 'minute')}` : unit(hours, 'hour');
}

/**
 * Rewrites ISO dates and long minute counts inside free text, such as chat replies,
 * so they read the same as the rest of the page.
 */
export function humaniseText(text: string): string {
 return text
  .replace(/\b(\d{4}-\d{2}-\d{2})(?![\d:T])/g, (match, iso: string) => { const formatted = formatDate(iso); return formatted === iso ? match : formatted; })
  .replace(/\b(\d{2,5})(\s?)(minutes|mins)\b/gi, (match, count: string) => Number(count) >= 60 ? formatDuration(Number(count)) : match);
}

/**
 * A runway length for display only: "24 weeks (5 months + 2 weeks)".
 * Short runways stay in weeks; spare days are stated rather than rounded away.
 */
export function formatRunwaySpan(weeks: number, extraDays = 0): string {
 const base = extraDays ? `${unit(weeks, 'week')}, ${unit(extraDays, 'day')}` : unit(weeks, 'week');
 const months = Math.floor(weeks / (52 / 12));
 if (months < 1) return base;
 const rest = Math.max(0, weeks - Math.round(months * 52 / 12));
 return `${base} (${unit(months, 'month')}${rest ? ` + ${unit(rest, 'week')}` : ''})`;
}
