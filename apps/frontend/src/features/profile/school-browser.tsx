"use client";
import { useEffect, useState } from 'react';
import { profileApi } from '@/lib/api/profile';
import type { Institution, SchoolCategory, SchoolResults } from './types';

// A suggestion only: browser settings do not establish the user's physical location.
export function suggestedCountry() {
  try {
    if (Intl.DateTimeFormat().resolvedOptions().timeZone === 'Asia/Singapore') return 'SG';
    return new Intl.Locale(navigator.language).region || '';
  } catch { return ''; }
}

export function SchoolBrowser({ category, onSelect, initialCountry = '', onCountryChange }: {
  category: SchoolCategory; onSelect?: (institution: Institution) => void;
  initialCountry?: string; onCountryChange?: (code: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState(initialCountry);
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([]);
  const [results, setResults] = useState<SchoolResults | null>(null);
  const [error, setError] = useState('');
  const [countryError, setCountryError] = useState('');
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (category !== 'university') return;
    const controller = new AbortController();
    setCountryError('');
    profileApi<{ code: string; name: string }[]>('/school-countries', { signal: controller.signal })
      .then(items => {
        if (controller.signal.aborted) return;
        setCountries(items);
        // A locale outside the directory must not leave an invisible active filter.
        setCountry(value => items.some(c => c.code === value) ? value : '');
      }).catch(e => { if (e.name !== 'AbortError') setCountryError('Countries could not load. Retry the directory.'); });
    return () => controller.abort();
  }, [category, retry]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    if (page === 0) setResults(null);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ category, q: query, offset: String(page * 25), limit: '25' });
      if (category === 'university' && country) params.set('country', country);
      profileApi<SchoolResults>(`/institutions?${params}`, { signal: controller.signal })
        .then(next => {
          if (!controller.signal.aborted) setResults(previous => ({ ...next,
            items: page && previous ? [...previous.items, ...next.items.filter(s => !previous.items.some(p => p.id === s.id))] : next.items }));
        }).catch(e => { if (e.name !== 'AbortError') setError('School suggestions could not load. Please retry.'); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [category, query, country, page, retry]);
  const groups = new Map<string, { name: string; schools: Institution[] }>();
  for (const school of results?.items || []) {
    const code = category === 'university' ? school.country_code : 'SG';
    if (!groups.has(code)) groups.set(code, { name: school.country, schools: [] });
    groups.get(code)!.schools.push(school);
  }
  return <div className="school-browser">
    <label>Search schools<input type="search" value={query} maxLength={150} placeholder="Start with your school’s name"
      onChange={e => { setQuery(e.target.value); setPage(0); }} /></label>
    {category === 'university' && <label>Country<select value={country}
      onChange={e => { setCountry(e.target.value); onCountryChange?.(e.target.value); setPage(0); }}><option value="">All countries</option>
      {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>}
    {(error || countryError) && <p role="alert">{error || countryError} <button type="button" onClick={() => setRetry(n => n + 1)}>Retry directory</button></p>}
    {results && <>
      <p aria-live="polite">{results.total.toLocaleString()} {results.total === 1 ? 'matching school' : 'matching schools'}</p>
      <div className="school-results" aria-label="School suggestions">
        {[...groups.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([code, group]) => <section key={code} aria-label={group.name} className="school-country">
          {category === 'university' && <h3>{group.name}</h3>}
          <ul>{group.schools.map(s => <li key={s.id}>{onSelect ? <button type="button" onClick={() => onSelect(s)}>{s.name}</button> : s.name}</li>)}</ul>
        </section>)}
      </div>
      {results.total === 0 && <p>No matching institution. Try all countries or enter an unlisted school.</p>}
      {results.items.length < results.total && <div className="pagination"><button type="button" disabled={loading || !!error} onClick={() => setPage(n => n + 1)}>Show more schools</button>
        <span className="muted">Showing {results.items.length} of {results.total.toLocaleString()}</span></div>}
      <p className="muted">Snapshot {results.snapshot_date}. {results.coverage_note}</p>
    </>}
    {loading && <p role="status">Loading suggestions…</p>}
  </div>;
}
