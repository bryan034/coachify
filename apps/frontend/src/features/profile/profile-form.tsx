"use client";
import { useEffect, useState, useRef, type FormEvent } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import { PlanningPreferences } from './planning-preferences';
import { useProfile } from './profile-provider';
import { PageTitle } from '@/components/ui/workspace-ui';
import { EmploymentSuggestions } from './employment-suggestions';
import { SchoolBrowser } from './school-browser';
import { EducationFields, editorFrom, educationPayload, type EducationEditor } from './education-fields';
import type { Institution } from './types';
import { educationQuestions, statuses, type Category, type OccupationalStatus, type Profile, type SchoolCategory } from './types';

export function ProfileForm({ initialSetup = false, onSaved, onCancel }: {
  initialSetup?: boolean; onSaved?: () => void; onCancel?: () => void;
}) {
  const preserveDraft = useRef(false);
  const pending = useRef<{signature:string;key:string}|null>(null);
  const { mode: authMode, token, profile, categories, loading, configError, loadError, reload, setProfile } = useProfile();
  const [noPrevious, setNoPrevious] = useState(false);
  const [employer, setEmployer] = useState('');
  const [role, setRole] = useState('');
  const [industry, setIndustry] = useState('');
  const [previouslyEmployed, setPreviouslyEmployed] = useState<boolean | null>(null);
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
  const educationSource = JSON.stringify([profile?.occupational_status, profile?.school_category, profile?.education, profile?.education_review_required, profile?.no_previous_education, profile?.employment, profile?.previously_employed]);
  useEffect(() => {
    if (preserveDraft.current) { preserveDraft.current=false; return; }
    setIndustry(profile?.employment?.industry || ''); setPreviouslyEmployed(profile?.previously_employed ?? null);
    setEmployer(profile?.employment?.employer || ''); setRole(profile?.employment?.role || '');
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
    if (status === 'unemployed' && previouslyEmployed === null) { setError('Tell us whether you were previously employed.'); return; }
    if (status === 'student' && !category) { setError('Choose a school category.'); return; }
    if (!token || !profile) { setError('Sign in and load your profile before saving.'); return; }
    setSaving(true);
    try {
      const education = noPrevious && status !== 'student' ? {} : educationPayload({ ...editor, graduationDirty: status === 'unemployed' && previouslyEmployed === false && editor.graduationDirty }, institutionDirty, status);
      const body = {expected_version:profile.version, occupational_status:status, school_category:category||null,
        no_previous_education:noPrevious&&status!=='student',
        ...(status==='unemployed'?{previously_employed:previouslyEmployed}:{}),
        ...((status==='employed'||(status==='unemployed'&&previouslyEmployed===true))?{employment:{employer:employer.trim()||null,role:role.trim()||null,industry:industry.trim()||null}}:{}),
        ...(Object.keys(education).length?{education}:{}),...(confirmed?{confirm_education_context:true}:{})};
      const signature=JSON.stringify(body);
      if(!pending.current||pending.current.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
      const updated=await profileApi<Profile>(finish?'/onboarding/complete':'',{
        method:finish?'POST':'PATCH',body:signature,...(finish?{headers:{'Idempotency-Key':pending.current.key}}:{}),
      },token);
      if(!setProfile(updated))return;
      pending.current=null;setEditor(editorFrom(updated.education));setInstitutionDirty(false);setConfirmed(false);setConflict(false);
      setMessage(finish?'Setup complete.':'Profile saved.');
      if (!finish) onSaved?.();

    } catch(e) {
      // A lost committed response is reconciled from the server, never inferred locally.
      if(finish&&(!(e instanceof ApiError)||e.status>=500)) {
        try {const latest=await profileApi<Profile>('',{},token);if(latest.onboarding_complete&&setProfile(latest)){return;}}catch{ /* Keep the current account's draft and retry key. */ }
      }
      setConflict(e instanceof ApiError&&e.status===409);
      setError(e instanceof Error?e.message:'Saving failed. Your selections are retained; please retry.');
    } finally {setSaving(false);}
  }
  const disabled = saving || loading || !authMode || needsSignIn || !profile || !!configError;
  function changeCategory(value: string) {
    setNoPrevious(value === 'none'); setCategory(value === 'none' ? '' : value as SchoolCategory);
    setExpanded(value && value !== 'none' && value !== category ? value as SchoolCategory : null); setConfirmed(false); setMessage('');
  }
  return <section className="profile-shell profile-editor page on">
    <PageTitle title={initialSetup ? "Finish your setup" : "Edit profile"} />
    <p className="profile-editor-description">Keep your background up to date. Make your changes below, then save when you’re ready.</p>
    {(configError || loadError) && <p role="alert" className="error">{configError || loadError}</p>}
    {loading && <p role="status">Loading your profile…</p>}
    <form onSubmit={event => void save(event)}>
      <fieldset className="profile-editor-section" disabled={disabled}>
        <legend>About you</legend>
        <label className="profile-editor-label">Occupational status<select value={status} onChange={e => {
          if (e.target.value === 'unemployed' && status !== 'unemployed') setPreviouslyEmployed(null);
          setStatus(e.target.value as OccupationalStatus | ''); if (e.target.value === 'student') setNoPrevious(false); setConfirmed(false); setMessage('');
        }}><option value="">Choose your status</option>{statuses.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
        {status === 'unemployed' && <label className="profile-editor-label">Were you previously employed?<select value={previouslyEmployed === null ? '' : String(previouslyEmployed)} onChange={e => setPreviouslyEmployed(e.target.value === '' ? null : e.target.value === 'true')}><option value="">Choose an answer</option><option value="true">Yes</option><option value="false">No</option></select></label>}
        {(status === 'employed' || (status === 'unemployed' && previouslyEmployed === true)) && <>
          <EmploymentSuggestions id="profile-employer" kind="companies" label={status === 'unemployed' ? 'Previous employer' : 'Place of employment'} value={employer} onChange={setEmployer} />
          <label className="profile-editor-label">Role<input type="text" maxLength={300} value={role} placeholder={status === 'unemployed' ? 'Your previous role' : 'Your current role'} onChange={e => setRole(e.target.value)} /></label>
          <EmploymentSuggestions id="profile-industry" kind="industries" label="Industry" value={industry} onChange={setIndustry} />
        </>}
      </fieldset>
      {status && <fieldset className="profile-editor-section" disabled={disabled}>
        <legend>{status === 'student' ? 'Current education' : 'Last education'}</legend>
        <label className="profile-editor-label">Education path<select value={noPrevious ? 'none' : category} onChange={e => changeCategory(e.target.value)}>
          <option value="">Choose your education path</option>{categories.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          {status !== 'student' && <option value="none">No applicable previous education</option>}
        </select></label>
        {!noPrevious && <>
          <div className="profile-editor-school">
            <div className="profile-editor-school-heading"><span>School or institution</span>
              {category && <button type="button" className="profile-inline-link" onClick={() => setExpanded(expanded ? null : category)}>{expanded ? 'Close school search' : editor.institutionName ? 'Change school' : 'Find your school'}</button>}
            </div>
            {editor.custom ? <input type="text" aria-label="Institution name" maxLength={300} value={editor.institutionName} onChange={e => { setEditor(previous => ({ ...previous, institutionName: e.target.value })); setInstitutionDirty(true); setMessage(''); }} /> : <p className="profile-editor-school-value">{editor.institutionName || 'No school selected'}</p>}
            {expanded && category && <div className="profile-editor-search">
              <SchoolBrowser key={category} category={category} onSelect={institution => chooseInstitution(institution, category)} />
              <button type="button" className="profile-inline-link" onClick={() => {
                setEditor(previous => ({ ...previous, custom: true, institution: undefined, institutionName: previous.custom ? previous.institutionName : '' }));
                setInstitutionDirty(true); setExpanded(null); setMessage('');
              }}>My institution is not listed</button>
            </div>}
          </div>
          {status === 'unemployed' && previouslyEmployed === false && <label className="profile-editor-label">Year of graduation<input type="number" min="1900" step="1" value={editor.graduation} onChange={e => setEditor({ ...editor, graduation: e.target.value, graduationDirty: true })} /></label>}
          <EducationFields status={status} category={category} editor={editor} setEditor={setEditor} />
        </>}
      </fieldset>}
      {(!noPrevious && (contextChanged || profile?.education_review_required)) && <div className="profile-editor-review">
        <p className="notice">Please review your education details for this status and category. Your previously saved details are retained.</p>
        <label className="review-confirm"><input type="checkbox" disabled={disabled} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I have reviewed the education details for this status and category.</label>
      </div>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status" className="success">{message}</p>}
      {(conflict || (!configError && !loadError && token && !profile && !loading)) && <button type="button" className="btn ghost" disabled={saving} onClick={conflict ? reconcile : reload}>
        {conflict ? 'Load latest saved values (keep draft)' : 'Retry loading'}</button>}
      <div className="profile-editor-actions">
        <span className="muted">Changes are saved only when you choose Save.</span>
        <div>{onCancel && <button type="button" className="btn ghost" disabled={saving} onClick={onCancel}>Cancel</button>}
          <button className="btn pri" type="submit" disabled={disabled || conflict || categories.length === 0}>{saving ? 'Saving…' : initialSetup ? 'Finish setup' : onSaved ? 'Save changes' : 'Save background'}</button>
          {initialSetup && <button type="button" className="btn ghost" disabled={disabled || conflict} onClick={() => void save(undefined, false)}>Save progress</button>}
        </div>
      </div>
    </form>
    {!initialSetup && !onCancel && <PlanningPreferences />}
    <footer>School suggestions: <a href="https://data.gov.sg/datasets/d_688b934f82c1059ed0a6993d2a829089/view">MOE / data.gov.sg</a> (accessed 24 October 2026, <a href="https://data.gov.sg/open-data-licence">Singapore Open Data Licence</a>) and <a href="https://github.com/Hipo/university-domains-list">Hipo university directory (MIT)</a>. Unlisted schools can be entered manually.</footer>
  </section>;
}
