import {describe,expect,it} from 'vitest';
import {dateSpan} from './dates';

describe('dateSpan', () => {
 it('shows a same-year range with its month count', () => expect(dateSpan('2026-06','2026-08')).toBe('Jun – Aug 2026 · 3 months'));
 it('keeps year-only precision without inventing a duration', () => expect(dateSpan('2022','2026')).toBe('2022 – 2026'));
 it('marks ongoing items as present', () => expect(dateSpan('2025-09',null,true)).toBe('Sep 2025 – present'));
 it('returns null when no date is stated', () => expect(dateSpan(null,null)).toBeNull());
});
