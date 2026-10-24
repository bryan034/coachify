import React from 'react';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { SchoolBrowser } from './school-browser';
const schools = [
  { id: 'sg-1', name: 'Synthetic Singapore University', country: 'Singapore', country_code: 'SG' },
  { id: 'us-1', name: 'Synthetic US University', country: 'United States', country_code: 'US' },
  { id: 'sg-2', name: 'Second Singapore University', country: 'Singapore', country_code: 'SG' },
];
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/school-countries')) return Response.json([{ code: 'SG', name: 'Singapore' }, { code: 'US', name: 'United States' }]);
    const params = new URL(url, 'http://synthetic.test').searchParams;
    const items = schools.filter(s => (!params.get('country') || s.country_code === params.get('country')) && (!params.get('q') || s.name.includes(params.get('q')!)));
    return Response.json({ items, total: items.length, snapshot_date: '2026-10-24', coverage_note: 'Synthetic directory' });
  }));
});
test('universities appear under country headings with names only in buttons', async () => {
  const select = vi.fn(); render(<SchoolBrowser category="university" onSelect={select} />);
  expect(await screen.findByRole('option', { name: 'All countries' })).toBeInTheDocument();
  const singapore = await screen.findByRole('region', { name: 'Singapore' });
  expect(within(singapore).getAllByRole('button').map(b => b.textContent)).toEqual(['Synthetic Singapore University', 'Second Singapore University']);
  expect(screen.getByRole('heading', { name: 'United States' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Select / })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Synthetic US University' })); expect(select).toHaveBeenCalledWith(schools[1]);
});
test('country default is editable and name search filters matching schools', async () => {
  render(<SchoolBrowser category="university" initialCountry="SG" onSelect={() => {}} />);
  await screen.findByRole('button', { name: 'Synthetic Singapore University' });
  expect(screen.queryByRole('heading', { name: 'United States' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '' } });
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'US' } });
  await screen.findByRole('button', { name: 'Synthetic US University' });
  expect(screen.queryByRole('heading', { name: 'Singapore' })).not.toBeInTheDocument();
});
test('an unsupported suggested country falls back to all countries', async () => {
  render(<SchoolBrowser category="university" initialCountry="XX" />);
  await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue(''));
  await screen.findByRole('heading', { name: 'United States' });
});

test('Show more appends schools under the same country without dropping earlier matches', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/school-countries')) return Response.json([{ code: 'SG', name: 'Singapore' }]);
    const offset = Number(new URL(url, 'http://synthetic.test').searchParams.get('offset'));
    const items = Array.from({ length: offset ? 1 : 25 }, (_, i) => ({ id: String(offset + i), name: `Synthetic School ${offset + i}`, country: 'Singapore', country_code: 'SG' }));
    return Response.json({ items, total: 26, snapshot_date: '2026-10-24', coverage_note: 'Synthetic directory' });
  }));
  render(<SchoolBrowser category="university" onSelect={() => {}} />);
  await screen.findByRole('button', { name: 'Synthetic School 0' });
  fireEvent.click(screen.getByRole('button', { name: 'Show more schools' }));
  await screen.findByRole('button', { name: 'Synthetic School 25' });
  expect(screen.getAllByRole('heading', { name: 'Singapore' })).toHaveLength(1);
  expect(within(screen.getByRole('region', { name: 'Singapore' })).getAllByRole('button')).toHaveLength(26);
  expect(screen.queryByRole('button', { name: 'Show more schools' })).not.toBeInTheDocument();
});
