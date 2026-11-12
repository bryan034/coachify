/** Preserve the precision supplied by the user; a year is not an exact date. */
export function partialDateBounds(value: string): [number, number] | null {
 if (!/^\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(value)) return null;
 const [year, month, day] = value.split('-').map(Number);
 if (year < 1 || year > 9999 || (month !== undefined && (month < 1 || month > 12))) return null;
 const lastDay = month === undefined ? 31 : [31,year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,31,30,31,30,31,31,30,31,30,31][month - 1];
 if (day !== undefined && (day < 1 || day > lastDay)) return null;
 return [year * 10000 + (month ?? 1) * 100 + (day ?? 1),year * 10000 + (month ?? 12) * 100 + (day ?? lastDay)];
}

export function dateInputError(start: string, end: string, ongoing: boolean): string | null {
 const from = start ? partialDateBounds(start) : null, to = end ? partialDateBounds(end) : null;
 if ((start && !from) || (end && !to)) return 'Use a valid YYYY, YYYY-MM or YYYY-MM-DD date, or leave it unknown.';
 if (ongoing && end) return 'An ongoing item cannot also have an end date.';
 if (from && to && from[0] > to[1]) return 'The start date cannot be after the end date.';
 return null;
}

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const parts = (value: string) => { const [year, month] = value.split('-'); return {year, month: month ? MONTHS[Number(month) - 1] : null}; };
/** "Jun – Aug 2026 · 3 months": only what the CV states, month count only when both ends have months. */
export function dateSpan(start?: string | null, end?: string | null, ongoing?: boolean): string | null {
 if (!start && !end) return null;
 const from = start && partialDateBounds(start) ? parts(start) : null, to = end && partialDateBounds(end) ? parts(end) : null;
 if (!from && !to) return null;
 const fromText = from ? [from.month, from.year].filter(Boolean).join(' ') : '';
 const toText = ongoing ? 'present' : to ? [to.month, to.year].filter(Boolean).join(' ') : '';
 const sameYear = from && to && from.year === to.year && from.month && to.month;
 const text = sameYear ? `${from.month} – ${toText}` : [fromText, toText].filter(Boolean).join(' – ');
 let months: number | null = null;
 if (start && end && /^\d{4}-\d{2}/.test(start) && /^\d{4}-\d{2}/.test(end)) {
  const [y1, m1] = start.split('-').map(Number), [y2, m2] = end.split('-').map(Number);
  months = (y2 - y1) * 12 + (m2 - m1) + 1;
 }
 return months && months > 0 ? `${text} · ${months} ${months === 1 ? 'month' : 'months'}` : text;
}
