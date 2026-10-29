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
