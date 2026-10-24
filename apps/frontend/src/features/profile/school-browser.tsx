"use client";
import { useEffect, useState } from 'react';
import { profileApi } from '@/lib/api/profile';
import type { Institution, SchoolCategory, SchoolResults } from './types';

export function SchoolBrowser({ category, onSelect }: { category: SchoolCategory; onSelect?: (institution: Institution) => void }) {
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState('');
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([]);
  const [results, setResults] = useState<SchoolResults | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (category !== 'university') return;
    const controller = new AbortController();
    profileApi<{ code: string; name: string }[]>('/school-countries', { signal: controller.signal })
      .then(setCountries).catch(e => { if (e.name !== 'AbortError') setError('Countries could not load. Retry the directory.'); });
    return () => controller.abort();
  }, [category, retry]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setResults(null);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ category, q: query, offset: String(page * 25), limit: '25' });
      if (category === 'university' && country) params.set('country', country);
      profileApi<SchoolResults>(`/institutions?${params}`, { signal: controller.signal })
        .then(setResults).catch(e => { if (e.name !== 'AbortError') setError('School suggestions could not load. Please retry.'); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [category, query, country, page, retry]);
  return <div className="school-browser">
    <label>Search schools<input type="search" value={query} maxLength={150}
      onChange={e => { setQuery(e.target.value); setPage(0); }} /></label>
    {category === 'university' && <label>Country / territory<select value={country}
      onChange={e => { setCountry(e.target.value); setPage(0); }}><option value="">All countries / territories</option>
      {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}</select></label>}
    {loading && <p role="status">Loading suggestions…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(n => n + 1)}>Retry directory</button></p>}
    {results && <>
      <p aria-live="polite">{results.total.toLocaleString()} {results.total === 1 ? 'suggestion' : 'suggestions'} · snapshot {results.snapshot_date}</p>
      <ul>{results.items.map(s => <li key={s.id}>{onSelect ? <button type="button" onClick={() => onSelect(s)}>Select {s.name}</button> : s.name} <span className="muted">{s.country}</span></li>)}</ul>
      {results.total === 0 && <p>No matching institution. An unlisted school remains valid.</p>}
      <div className="pagination"><button type="button" disabled={page === 0} onClick={() => setPage(n => n - 1)}>Previous</button>
        <button type="button" disabled={(page + 1) * 25 >= results.total} onClick={() => setPage(n => n + 1)}>Next</button></div>
      <p className="muted">{results.coverage_note}</p>
    </>}
    <p className="muted">Select a suggestion, or enter your institution’s name below if it is not listed.</p>
  </div>;
}
