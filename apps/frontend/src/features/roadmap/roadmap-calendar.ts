import { formatDate } from '@/lib/format';
const parse = (value: string) => new Date(`${value}T12:00:00Z`);
const iso = (date: Date) => date.toISOString().slice(0, 10);
const format = (value: string, options: Intl.DateTimeFormatOptions) => parse(value).toLocaleDateString('en-SG', { ...options, timeZone: 'UTC' });

export const addDays = (value: string, count: number) => { const date = parse(value); date.setUTCDate(date.getUTCDate() + count); return iso(date); };
export const weekStart = (value: string, startDay = 0) => addDays(value, -((parse(value).getUTCDay() + 6 - startDay + 7) % 7));
export const weekDates = (value: string, startDay = 0) => { const monday = weekStart(value, startDay); return Array.from({ length: 7 }, (_, index) => addDays(monday, index)); };
export const monthKey = (value: string) => value.slice(0, 7);
export const addMonths = (value: string, count: number) => { const date = new Date(Date.UTC(Number(value.slice(0, 4)), Number(value.slice(5, 7)) - 1 + count, 1, 12)); return iso(date); };

export function monthWeeks(value: string, startDay = 0) {
 const first = `${monthKey(value)}-01`; const weeks: string[] = [];
 for (let monday = weekStart(first, startDay); monthKey(monday) <= monthKey(value); monday = addDays(monday, 7)) weeks.push(monday);
 return weeks;
}
export function monthsBetween(start: string, end: string) {
 const months: string[] = [];
 for (let month = `${monthKey(start)}-01`; monthKey(month) <= monthKey(end); month = addMonths(month, 1)) months.push(month);
 return months;
}
export function weekColumns(monday: string, start: string, end: string) {
 const sunday = addDays(monday, 6);
 if (end < monday || start > sunday) return null;
 const from = start < monday ? 1 : (parse(start).getTime() - parse(monday).getTime()) / 86400000 + 1;
 const to = end > sunday ? 7 : (parse(end).getTime() - parse(monday).getTime()) / 86400000 + 1;
 return { from, to, startsHere: start >= monday, endsHere: end <= sunday };
}
export const clockRange = (start: string, minutes: number) => {
 const [hour, minute] = start.split(':').map(Number); const end = hour * 60 + minute + minutes;
 return `${start}–${String(Math.floor(end / 60)).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`;
};
export const dayOfMonth = (value: string) => Number(value.slice(8));
export const weekdayName = (value: string) => format(value, { weekday: 'short' });
export const shortDate = (value: string) => format(value, { day: 'numeric', month: 'short' });
export const fullDate = (value: string) => formatDate(value);
export const monthName = (value: string) => format(value, { month: 'short' });
export const monthTitle = (value: string) => format(value, { month: 'long', year: 'numeric' });
