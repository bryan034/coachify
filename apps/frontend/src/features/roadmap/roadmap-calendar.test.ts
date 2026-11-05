import { describe, expect, it } from 'vitest';
import { addDays, addMonths, clockRange, monthWeeks, monthsBetween, weekColumns, weekDates, weekStart } from './roadmap-calendar';

describe('roadmap calendar', () => {
 it('uses Monday-to-Sunday weeks, including across month and year ends', () => {
  expect(weekStart('2030-01-09')).toBe('2030-01-07');
  expect(weekStart('2030-01-07')).toBe('2030-01-07');
  expect(weekStart('2030-01-13')).toBe('2030-01-07');
  expect(weekStart('2030-01-01')).toBe('2029-12-31');
  expect(weekDates('2030-01-09')).toEqual(['2030-01-07', '2030-01-08', '2030-01-09', '2030-01-10', '2030-01-11', '2030-01-12', '2030-01-13']);
 });
 it('moves by days and months without skipping short months', () => {
  expect(addDays('2030-02-28', 1)).toBe('2030-03-01');
  expect(addMonths('2030-01-31', 1)).toBe('2030-02-01');
  expect(addMonths('2030-01-15', -1)).toBe('2029-12-01');
 });
 it('lists every week that touches a month', () => {
  expect(monthWeeks('2030-01-15')).toEqual(['2029-12-31', '2030-01-07', '2030-01-14', '2030-01-21', '2030-01-28']);
  // February 2027 starts on a Monday and fills exactly four weeks.
  expect(monthWeeks('2027-02-10')).toEqual(['2027-02-01', '2027-02-08', '2027-02-15', '2027-02-22']);
 });
 it('lists the months between two dates', () => {
  expect(monthsBetween('2029-11-20', '2030-02-02')).toEqual(['2029-11-01', '2029-12-01', '2030-01-01', '2030-02-01']);
 });
 it('finds the columns a milestone covers in a week', () => {
  expect(weekColumns('2030-01-07', '2030-01-09', '2030-01-20')).toEqual({ from: 3, to: 7, startsHere: true, endsHere: false });
  expect(weekColumns('2030-01-14', '2030-01-09', '2030-01-20')).toEqual({ from: 1, to: 7, startsHere: false, endsHere: true });
  expect(weekColumns('2030-01-21', '2030-01-09', '2030-01-20')).toBeNull();
 });
 it('writes a session as a clock range', () => {
  expect(clockRange('19:00', 90)).toBe('19:00–20:30');
  expect(clockRange('23:00', 60)).toBe('23:00–24:00');
 });
});
