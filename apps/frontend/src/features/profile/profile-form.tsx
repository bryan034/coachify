"use client";
import { useEffect, useState, useRef, type FormEvent } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import { PlanningPreferences } from './planning-preferences';
import { AccountPanel } from './account-panel';
import { useProfile } from './profile-provider';
import { PageTitle } from '@/components/ui/workspace-ui';
import { SchoolBrowser } from './school-browser';
import { EducationFields, editorFrom, educationPayload, type EducationEditor } from './education-fields';
import type { Institution } from './types';
import { educationQuestions, statuses, type Category, type OccupationalStatus, type Profile, type SchoolCategory } from './types';

export function ProfileForm({ initialSetup = false }: { initialSetup?: boolean }) {
  const preserveDraft = useRef(false);
  const pending = useRef<{signature:string;key:string}|null>(null);
  const { mode: authMode, token, profile, categories, loading, configError, loadError, reload, setProfile } = useProfile();
  const [noPrevious, setNoPrevious] = useState(false);
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
  const educationSource = JSON.stringify([profile?.occupational_status, profile?.school_category, profile?.education, profile?.education_review_required, profile?.no_previous_education]);
  useEffect(() => {
    if (preserveDraft.current) { preserveDraft.current=false; return; }
    setNoPrevious(profile?.no_previous_education || false);
    setStatus(profile?.occupational_status || ''); setCategory(profile?.school_category || '');
    setEditor(editorFrom(profile?.education || {})); setInstitutionDirty(false); setConfirmed(false);
    setConflict(false); setError('');
  }, [educationSource]);
  const needsSignIn = !token;
  const contextChanged = !!profile?.occupational_status && (status !== profile.occupational_status || (category || null) !== profile.school_category);
  function chooseInstitution(institution: Institution, selectedCategory: Category['id']) {
    setNoPrevious(false); setCategory(selectedCategory); setExpanded(null); setInstitutionDirty(true); setMessage('');
    setEditor(previous => ({ ...previous, institution: { kind: 'catalogue', id: institution.id }, institutionName: institution.name, custom: false }));
  }
  async function reconcile() {
    try {
      const latest=await profileApi<Profile>('',{},token);
      preserveDraft.current=true;
      if(!setProfile(latest)) { preserveDraft.current=false; return; }
      setConflict(false);setMessage('Latest saved values loaded. Your draft is retained; review it before saving.');
    } catch(e) {setError((e as Error).message);}
  }
  async function save(event?: FormEvent, finish = initialSetup) {
    event?.preventDefault(); setError(''); setMessage('');
    if (!status) { setError('Choose your occupational status.'); return; }
    if (status === 'student' && !category) { setError('Choose a school category.'); return; }
    if (!token || !profile) { setError('Sign in and load your profile before saving.'); return; }
    setSaving(true);
    try {
      const education = noPrevious && status !== 'student' ? {} : educationPayload(editor, institutionDirty, status);
      const body = {expected_version:profile.version, occupational_status:status, school_category:category||null,
        no_previous_education:noPrevious&&status!=='student',
        ...(Object.keys(education).length?{education}:{}),...(confirmed?{confirm_education_context:true}:{})};
      const signature=JSON.stringify(body);
      if(!pending.current||pending.current.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
      const updated=await profileApi<Profile>(finish?'/onboarding/complete':'',{
        method:finish?'POST':'PATCH',body:signature,...(finish?{headers:{'Idempotency-Key':pending.current.key}}:{}),
      },token);
      if(!setProfile(updated))return;
      pending.current=null;setEditor(editorFrom(updated.education));setInstitutionDirty(false);setConfirmed(false);setConflict(false);
      setMessage(finish?'Setup complete.':'Profile saved.');

    } catch(e) {
      // A lost committed response is reconciled from the server, never inferred locally.
      if(finish&&(!(e instanceof ApiError)||e.status>=500)) {
        try {const latest=await profileApi<Profile>('',{},token);if(latest.onboarding_complete&&setProfile(latest)){return;}}catch{ /* Keep the current account's draft and retry key. */ }
      }
      setConflict(e instanceof ApiError&&e.status===409);
      setError(e instanceof Error?e.message:'Saving failed. Your selections are retained; please retry.');
    } finally {setSaving(false);}
  }
  return <section className="profile-shell page on">
    <PageTitle title={initialSetup?"Finish your setup":"My profile"}><span className="chip">Your starting point</span></PageTitle>
    <div className="intro"><p className="k">01 / Background</p><h2>A little about where you are now.</h2>
      <p className="small">Your background helps shape a practical path towards your target role.</p></div>
    <AccountPanel busy={saving}/>
    {loading && <p role="status">Loading your profile…</p>}
    <form onSubmit={event=>void save(event)}>
      <div className="profile-form-grid">
      <fieldset className="card" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError}>
        <legend>What is your occupational status?</legend><p className="muted">Choose the option that best describes you today.</p>
        <div className="status-grid">{statuses.map(s => <label key={s.id} className={status === s.id ? 'status-option selected' : 'status-option'}>
          <input type="radio" name="occupational_status" value={s.id} checked={status === s.id}
            onChange={() => { setStatus(s.id); if(s.id==='student')setNoPrevious(false); setConfirmed(false); setMessage(''); }} />{s.label}</label>)}</div>
      </fieldset>
      {status && <fieldset className="card" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError}>
        <legend>{educationQuestions(status).institution}</legend>
        <p className="muted">Choose your school category to search, or enter an unlisted institution below.</p>
        {categories.map(c => <details key={c.id} className={category === c.id ? 'category-group selected-category' : 'category-group'} open={expanded === c.id}>
          <summary onClick={event => {
            event.preventDefault();
            setNoPrevious(false); setCategory(c.id); setExpanded(expanded === c.id ? null : c.id); setConfirmed(false); setMessage('');
          }}><span>{c.label}</span>{category === c.id && <span className="category-badge">Selected</span>}</summary>
          <div className="category-content">
            {expanded === c.id && <SchoolBrowser category={c.id} onSelect={institution => chooseInstitution(institution, c.id)} />}
          </div>
        </details>)}
        {status !== 'student' && <label className="category-choice no-education"><input type="radio" name="school_category" value=""
          checked={!category&&noPrevious} onChange={() => { setNoPrevious(true); setCategory(''); setConfirmed(false); setMessage(''); }} />No applicable previous education</label>}
        {!noPrevious && <EducationFields status={status} category={category} editor={editor} setEditor={setEditor}
          onInstitutionDirty={() => { setInstitutionDirty(true); setMessage(''); }} />}
      </fieldset>}
      </div>
      {(!noPrevious && (contextChanged || profile?.education_review_required)) && <p role="status" className="notice">Please review your education details for this status and category. Previously saved education is retained; it has not been moved or relabelled.</p>}
      {(!noPrevious && (contextChanged || profile?.education_review_required)) && <label className="review-confirm"><input type="checkbox" disabled={saving || loading || !authMode || needsSignIn || !profile || !!configError} checked={confirmed}
        onChange={event => setConfirmed(event.target.checked)} />I have reviewed the education details for this status and category.</label>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status" className="success">{message}</p>}
      {(conflict || (!configError && !loadError && token && !profile && !loading)) && <button type="button" disabled={saving} onClick={conflict ? reconcile : reload}>
        {conflict ? 'Load latest saved values (keep draft)' : 'Retry loading'}</button>}
      <div className="save-row"><span className="muted">Your answers can be updated later.</span><button className="primary" type="submit" disabled={saving || loading || !token || !profile || conflict || !!configError || categories.length === 0}>
        {saving ? 'Saving…' : initialSetup ? 'Finish setup' : 'Save background'}</button>{initialSetup&&<button type="button" className="btn ghost" disabled={saving||loading||!profile||conflict} onClick={()=>void save(undefined,false)}>Save progress</button>}</div>
    </form>
    {!initialSetup && <PlanningPreferences/>}
    <footer>School suggestions use local snapshots. Contains information from MOE’s <a href="https://data.gov.sg/datasets/d_688b934f82c1059ed0a6993d2a829089/view">General information of schools</a>, accessed 24 October 2026, under the <a href="https://data.gov.sg/open-data-licence">Singapore Open Data Licence</a>. International suggestions: <a href="https://github.com/Hipo/university-domains-list">Hipo university directory (MIT)</a>. Neither source verifies enrolment or accreditation.</footer>
  </section>;
}
