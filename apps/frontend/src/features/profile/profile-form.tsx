"use client";
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import { AccountPanel } from './account-panel';
import { useProfile } from './profile-provider';
import { PageTitle } from '@/components/ui/workspace-ui';
import { SchoolBrowser } from './school-browser';
import { EducationFields, editorFrom, educationPayload, type EducationEditor } from './education-fields';
import type { Institution } from './types';
import { educationQuestions, statuses, type Category, type OccupationalStatus, type Profile, type SchoolCategory } from './types';

export function ProfileForm() {
  const { mode: authMode, token, profile, categories, loading, configError, loadError, reload, setProfile } = useProfile();
  const [status, setStatus] = useState<OccupationalStatus | ''>('');
  const [category, setCategory] = useState<SchoolCategory | ''>('');
  const [editor, setEditor] = useState<EducationEditor>(() => editorFrom({}));
  const [institutionDirty, setInstitutionDirty] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [expanded, setExpanded] = useState<SchoolCategory | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  useEffect(() => {
    setStatus(profile?.occupational_status || ''); setCategory(profile?.school_category || '');
    setEditor(editorFrom(profile?.education || {})); setInstitutionDirty(false); setConfirmed(false);
    setConflict(false); setError('');
  }, [profile]);
  const needsSignIn = authMode === 'google' && !token;
  const contextChanged = !!profile?.occupational_status && (status !== profile.occupational_status || (category || null) !== profile.school_category);
  function chooseInstitution(institution: Institution, selectedCategory: Category['id']) {
    setCategory(selectedCategory); setExpanded(null); setInstitutionDirty(true); setMessage('');
    setEditor(previous => ({ ...previous, institution: { kind: 'catalogue', id: institution.id }, institutionName: institution.name, custom: false }));
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setError(''); setMessage('');
    if (!status) { setError('Choose your occupational status.'); return; }
    if (status === 'student' && !category) { setError('Choose a school category.'); return; }
    if (!(authMode === 'local_test' || (authMode === 'google' && token)) || !profile) { setError('Sign in and load your profile before saving.'); return; }
    setSaving(true);
    try {
      const education = educationPayload(editor, institutionDirty, status);
      const updated = await profileApi<Profile>('', { method: 'PATCH', body: JSON.stringify({
        expected_version: profile.version, occupational_status: status, school_category: category || null,
        ...(Object.keys(education).length ? { education } : {}),
        ...(confirmed ? { confirm_education_context: true } : {}),
      }) }, token);
      setProfile(updated); setEditor(editorFrom(updated.education)); setInstitutionDirty(false); setConfirmed(false); setConflict(false); setMessage('Profile saved.');
    } catch (e) {
      setConflict(e instanceof ApiError && e.status === 409);
      setError(e instanceof Error ? e.message : 'Saving failed. Your selections are retained; please retry.');
    } finally { setSaving(false); }
  }
  return <section className="profile-shell page on">
    <PageTitle title="My profile"><span className="chip">Your starting point</span></PageTitle>
    <div className="intro"><p className="k">01 / Background</p><h2>A little about where you are now.</h2>
      <p className="small">Your background helps shape a practical path towards your target role.</p></div>
    <AccountPanel busy={saving}/>
    {loading && <p role="status">Loading your profile…</p>}
    <form onSubmit={save}>
      <div className="profile-form-grid">
      <fieldset className="card" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError}>
        <legend>What is your occupational status?</legend><p className="muted">Choose the option that best describes you today.</p>
        <div className="status-grid">{statuses.map(s => <label key={s.id} className={status === s.id ? 'status-option selected' : 'status-option'}>
          <input type="radio" name="occupational_status" value={s.id} checked={status === s.id}
            onChange={() => { setStatus(s.id); setConfirmed(false); setMessage(''); }} />{s.label}</label>)}</div>
      </fieldset>
      {status && <fieldset className="card" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError}>
        <legend>{educationQuestions(status).institution}</legend>
        <p className="muted">Choose your school category to search, or enter an unlisted institution below.</p>
        {categories.map(c => <details key={c.id} className={category === c.id ? 'category-group selected-category' : 'category-group'} open={expanded === c.id}>
          <summary onClick={event => {
            event.preventDefault();
            setCategory(c.id); setExpanded(expanded === c.id ? null : c.id); setConfirmed(false); setMessage('');
          }}><span>{c.label}</span>{category === c.id && <span className="category-badge">Selected</span>}</summary>
          <div className="category-content">
            {expanded === c.id && <SchoolBrowser category={c.id} onSelect={institution => chooseInstitution(institution, c.id)} />}
          </div>
        </details>)}
        {status !== 'student' && <label className="category-choice no-education"><input type="radio" name="school_category" value=""
          checked={!category} onChange={() => { setCategory(''); setConfirmed(false); setMessage(''); }} />No applicable previous education</label>}
        <EducationFields status={status} category={category} editor={editor} setEditor={setEditor}
          onInstitutionDirty={() => { setInstitutionDirty(true); setMessage(''); }} />
      </fieldset>}
      </div>
      {(contextChanged || profile?.education_review_required) && <p role="status" className="notice">Please review your education details for this status and category. Previously saved education is retained; it has not been moved or relabelled.</p>}
      {(contextChanged || profile?.education_review_required) && <label className="review-confirm"><input type="checkbox" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError} checked={confirmed}
        onChange={event => setConfirmed(event.target.checked)} />I have reviewed the education details for this status and category.</label>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status" className="success">{message}</p>}
      {(conflict || (!configError && !loadError && (authMode === 'local_test' || token) && !profile && !loading)) && <button type="button" disabled={saving} onClick={reload}>
        {conflict ? 'Reload saved profile (replace unsaved selections)' : 'Retry loading'}</button>}
      <div className="save-row"><span className="muted">Your answers can be updated later.</span><button className="primary" type="submit" disabled={saving || loading || !(authMode === 'local_test' || (authMode === 'google' && token)) || !profile || conflict || !!configError || categories.length === 0}>
        {saving ? 'Saving…' : 'Save background'}</button></div>
    </form>
    <footer>School suggestions use local snapshots. Contains information from MOE’s <a href="https://data.gov.sg/datasets/d_688b934f82c1059ed0a6993d2a829089/view">General information of schools</a>, accessed 24 October 2026, under the <a href="https://data.gov.sg/open-data-licence">Singapore Open Data Licence</a>. International suggestions: <a href="https://github.com/Hipo/university-domains-list">Hipo university directory (MIT)</a>. Neither source verifies enrolment or accreditation.</footer>
  </section>;
}
