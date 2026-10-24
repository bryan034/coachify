"use client";
import { useEffect, useState } from 'react';
import { profileApi } from '@/lib/api/profile';

type Option = { id: string; name: string };
export function EmploymentSuggestions({ id, kind, label, value, onChange }: {
  id: string; kind: 'companies' | 'industries'; label: string; value: string; onChange: (value: string) => void;
}) {
  const [focused, setFocused] = useState(false);
  const [options, setOptions] = useState<Option[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!focused) return;
    const controller = new AbortController();
    setOptions([]); setFailed(false); setLoading(true);
    const timer = setTimeout(() => {
      void profileApi<Option[]>(`/${kind}?q=${encodeURIComponent(value.slice(0, 150))}&limit=8`, { signal: controller.signal }).then(rows => {
        if (!controller.signal.aborted) setOptions(Array.isArray(rows) ? rows : []);
      }).catch(() => { if (!controller.signal.aborted) setFailed(true); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [kind, value, focused]);
  return <div className="employment-suggestions profile-editor-label" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
  }}>
    <label htmlFor={id}>{label}</label>
    <input id={id} type="text" autoComplete="off" maxLength={300} value={value} aria-describedby={`${id}-hint`}
      placeholder={kind === 'companies' ? 'Search or enter a company name' : 'Search or enter an industry'}
      onFocus={() => setFocused(true)} onChange={event => onChange(event.target.value)} />
    {focused && options.length > 0 && <ul className="employment-options" aria-label={`${label} suggestions`}>{options.map(option => <li key={option.id}>
      <button type="button" onClick={() => { onChange(option.name); setFocused(false); }}>{option.name}</button>
    </li>)}</ul>}
    <p id={`${id}-hint`} className="employment-hint">{focused && loading ? 'Finding suggestions… ' : focused && failed ? 'Suggestions are unavailable. ' : focused && !options.length ? 'No matching suggestions. ' : ''}You can type your own {kind === 'companies' ? 'company' : 'industry'} name.</p>
  </div>;
}
