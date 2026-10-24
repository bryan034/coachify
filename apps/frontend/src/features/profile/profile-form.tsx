"use client";
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import { GoogleSignIn } from '@/lib/auth/google-sign-in';
import { SchoolBrowser } from './school-browser';
import { educationQuestions, statuses, type Category, type OccupationalStatus, type Profile, type SchoolCategory } from './types';

export function ProfileForm() {
  const [token, setToken] = useState<string>();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [status, setStatus] = useState<OccupationalStatus | ''>('');
  const [category, setCategory] = useState<SchoolCategory | ''>('');
  const [categories, setCategories] = useState<Category[]>([]);
  const [expanded, setExpanded] = useState<SchoolCategory[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [retry, setRetry] = useState(0);
  const onCredential = useCallback((credential: string) => setToken(credential), []);
  useEffect(() => {
    const controller = new AbortController();
    profileApi<Category[]>('/school-categories', { signal: controller.signal }).then(setCategories)
      .catch(e => { if (e.name !== 'AbortError') setError('School categories could not load. Check the profile service and retry.'); });
    return () => controller.abort();
  }, [retry]);
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    setLoading(true); setError(''); setProfile(null); setMessage(''); setConflict(false);
    profileApi<Profile>('', { signal: controller.signal }, token).then(p => {
      setProfile(p); setStatus(p.occupational_status || ''); setCategory(p.school_category || '');
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message || 'Profile could not load. Please retry.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, retry]);
  const contextChanged = !!profile?.occupational_status && (status !== profile.occupational_status || (category || null) !== profile.school_category);
  async function save(event: FormEvent) {
    event.preventDefault(); setError(''); setMessage('');
    if (!status) { setError('Choose your occupational status.'); return; }
    if (status === 'student' && !category) { setError('Choose a school category.'); return; }
    if (!token || !profile) { setError('Sign in and load your profile before saving.'); return; }
    setSaving(true);
    try {
      const updated = await profileApi<Profile>('', { method: 'PATCH', body: JSON.stringify({
        expected_version: profile.version, occupational_status: status, school_category: category || null,
      }) }, token);
      setProfile(updated); setConflict(false); setMessage('Profile saved.');
    } catch (e) {
      setConflict(e instanceof ApiError && e.status === 409);
      setError(e instanceof Error ? e.message : 'Saving failed. Your selections are retained; please retry.');
    } finally { setSaving(false); }
  }
  function signOut() {
    window.google?.accounts.id.disableAutoSelect();
    setToken(undefined); setProfile(null); setStatus(''); setCategory(''); setError(''); setMessage(''); setConflict(false);
  }
  return <main className="profile-shell">
    <header><a className="brand" href="/profile">coachify<span>·</span></a><span className="eyebrow">YOUR STARTING POINT</span></header>
    <section className="intro"><p className="eyebrow">01 / BACKGROUND</p><h1>A little about where you are now.</h1>
      <p>Your background helps shape a practical path towards your target role.</p></section>
    <section className="card auth-card" aria-label="Account">
      {token ? <><p>Google account connected. {profile && 'Your saved background is loaded.'}</p><button type="button" disabled={saving || loading} onClick={signOut}>Sign out</button></>
        : <><p>Sign in to save and return to your profile.</p><GoogleSignIn onCredential={onCredential} /></>}
    </section>
    {loading && <p role="status">Loading your profile…</p>}
    <form onSubmit={save}>
      <fieldset className="card" disabled={saving || loading}>
        <legend>What is your occupational status?</legend><p className="muted">Choose the option that best describes you today.</p>
        <div className="status-grid">{statuses.map(s => <label key={s.id} className={status === s.id ? 'status-option selected' : 'status-option'}>
          <input type="radio" name="occupational_status" value={s.id} checked={status === s.id}
            onChange={() => { setStatus(s.id); setMessage(''); }} />{s.label}</label>)}</div>
      </fieldset>
      {status && <fieldset className="card" disabled={saving || loading}>
        <legend>{educationQuestions(status).institution}</legend>
        <p className="muted">Choose a category, then explore school suggestions. Universities include international institutions.</p>
        {categories.map(c => <details key={c.id} className="category-group" onToggle={event => {
          const open = event.currentTarget.open;
          setExpanded(previous => open ? (previous.includes(c.id) ? previous : [...previous, c.id]) : previous.filter(id => id !== c.id));
        }}>
          <summary>{c.label}</summary><div className="category-content"><label className="category-choice">
            <input type="radio" name="school_category" value={c.id} checked={category === c.id}
              onChange={() => { setCategory(c.id); setMessage(''); }} />Use this category: {c.label}</label>
            {expanded.includes(c.id) && <SchoolBrowser category={c.id} />}</div></details>)}
        {status !== 'student' && <label className="category-choice no-education"><input type="radio" name="school_category" value=""
          checked={!category} onChange={() => { setCategory(''); setMessage(''); }} />No applicable previous education</label>}
      </fieldset>}
      {(contextChanged || profile?.education_review_required) && <p role="status" className="notice">Please review your education details for this status and category. Previously saved education is retained; it has not been moved or relabelled.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status" className="success">{message}</p>}
      {(conflict || (token && !profile && !loading) || categories.length === 0) && <button type="button" disabled={saving} onClick={() => setRetry(n => n + 1)}>
        {conflict ? 'Reload saved profile (replace unsaved selections)' : 'Retry loading'}</button>}
      <div className="save-row"><span className="muted">Your answers can be updated later.</span><button className="primary" type="submit" disabled={saving || loading || !token || !profile || conflict || categories.length === 0}>
        {saving ? 'Saving…' : 'Save background'}</button></div>
    </form>
    <footer>School suggestions use local snapshots. Contains information from MOE’s <a href="https://data.gov.sg/datasets/d_688b934f82c1059ed0a6993d2a829089/view">General information of schools</a>, accessed 24 October 2026, under the <a href="https://data.gov.sg/open-data-licence">Singapore Open Data Licence</a>. International suggestions: <a href="https://github.com/Hipo/university-domains-list">Hipo university directory (MIT)</a>. Neither source verifies enrolment or accreditation.</footer>
  </main>;
}
