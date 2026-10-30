"use client";
import { BrandLogo } from '@/components/ui/brand-logo';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, profileApi } from '@/lib/api/profile';
import { useProfile } from './profile-provider';
import { EmploymentSuggestions } from './employment-suggestions';
import { SchoolBrowser, suggestedCountry } from './school-browser';
import { editorFrom, graduationYear, type EducationEditor } from './education-fields';
import { educationQuestions, statuses, studyYearLabel, type EducationDraft, type OccupationalStatus, type Profile, type SchoolCategory } from './types';

type Step = 'status' | 'previous' | 'employer' | 'role' | 'industry' | 'pathway' | 'school' | 'graduation' | 'course' | 'year' | 'review';
const labels: Record<Step, string> = { status: 'Your starting point', previous: 'Your work history', industry: 'Your industry', employer: 'Your workplace', role: 'Your role', pathway: 'Education path', school: 'Your school', graduation: 'Graduation year', course: 'Your course', year: 'Study year', review: 'Ready to begin' };
const statusNotes = { student: 'Building your foundation.', national_service: 'Preparing for your next chapter.', unemployed: 'Exploring your next opportunity.', employed: 'Planning your next move.' };
const pathwayNotes = { secondary: 'Your learning starts here', ite: 'Skills for the real world', polytechnic: 'Learning through practice', junior_college: 'A foundation for what’s next', university: 'Singapore and around the world' };
function resumeStep(profile: Profile): Step {
  if (!profile.occupational_status) return 'status';
  if (profile.occupational_status === 'unemployed' && profile.previously_employed == null) return 'previous';
  const work = profile.occupational_status === 'employed' || (profile.occupational_status === 'unemployed' && profile.previously_employed === true);
  if (work && !profile.employment?.industry && profile.employment?.employer && profile.employment?.role) return 'industry';
  if (work && !profile.employment?.employer) return 'employer';
  if (work && !profile.employment?.role) return 'role';
  if (profile.no_previous_education && profile.occupational_status !== 'student' && !profile.school_category) return 'review';
  if (!profile.school_category) return 'pathway';
  if (!profile.education.institution || profile.education_review_required) return 'school';
  if (profile.occupational_status === 'unemployed' && profile.previously_employed === false && !profile.education.graduation_year) return 'graduation';
  if (!profile.education.course) return 'course';
  if (profile.occupational_status === 'student' && (!profile.education.study_year || profile.education.study_year_category !== profile.school_category)) return 'year';
  return 'review';
}

export function OnboardingFlow({ preview = false }: { preview?: boolean }) {
  const { profile, token, categories, setProfile, signOut } = useProfile();
  const router = useRouter();
  const initial = preview ? { ...profile!, occupational_status: null, school_category: null, no_previous_education: false, education: {}, previously_employed: null, employment: { employer: null, role: null, industry: null } } : profile!;
  const reviewRequired = !preview && !!profile?.education_review_required &&
    [profile?.education.institution, profile?.education.course, profile?.education.study_year, profile?.education.graduation_year].some(value => value != null);
  // The guard mounts this component only after canonical profile/session readback.
  const [step, setStep] = useState<Step>(() => preview ? 'status' : resumeStep(profile!));
  const [status, setStatus] = useState<OccupationalStatus | ''>(initial?.occupational_status || '');
  const [category, setCategory] = useState<SchoolCategory | ''>(initial?.school_category || '');
  const [editor, setEditor] = useState<EducationEditor>(() => editorFrom(initial?.education || {}));
  const [noPrevious, setNoPrevious] = useState(!!initial?.no_previous_education);
  const [custom, setCustom] = useState(initial?.education.institution?.kind === 'custom');
  const [employer, setEmployer] = useState(initial.employment?.employer || '');
  const [role, setRole] = useState(initial.employment?.role || '');
  const [industry, setIndustry] = useState(initial.employment?.industry || '');
  const [previouslyEmployed, setPreviouslyEmployed] = useState<boolean | null>(initial.previously_employed ?? null);
  const [country, setCountry] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [saveNote, setSaveNote] = useState('Your saved answers stay with your account.');
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLElement>(null);
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [changing, setChanging] = useState(false);
  const transition = useRef<Animation | null>(null);
  const lock = useRef(false);
  const alive = useRef(true);
  const latest = useRef(profile);
  latest.current = profile;
  const pending = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => { alive.current = true; setCountry(profile?.education.institution?.country_code || suggestedCountry()); return () => { alive.current = false; transition.current?.cancel(); }; }, []); // Account-scoped component; no persistent browser drafts.
  useEffect(() => { heading.current?.focus(); panel.current?.closest('.onboarding-body')?.scrollTo?.({ top: 0, behavior: 'instant' }); }, [step]);
  const student = status === 'student';
  const needsGraduation = status === 'unemployed' && previouslyEmployed === false;
  const afterSchool: Step = needsGraduation ? 'graduation' : 'course';
  const hasWork = status === 'employed' || (status === 'unemployed' && previouslyEmployed === true);
  const steps: Step[] = ['status', ...(status === 'unemployed' ? ['previous'] as Step[] : []), ...(hasWork ? ['employer', 'role', 'industry'] as Step[] : []), 'pathway',
    ...(!noPrevious ? ['school', ...(needsGraduation ? ['graduation'] as Step[] : []), 'course', ...(student || !status ? ['year'] as Step[] : [])] as Step[] : []), 'review'];
  const index = steps.indexOf(step);
  const questions = educationQuestions(status || 'student');
  function go(next: Step) {
    if (next === step || transition.current) return;
    const order: Step[] = ['status', 'previous', 'employer', 'role', 'industry', 'pathway', 'school', 'graduation', 'course', 'year', 'review'];
    const backwards = order.indexOf(next) < order.indexOf(step);
    setDirection(backwards ? 'backward' : 'forward');
    function arrive() { setStep(next); setError(''); setConfirmed(false); setChanging(false); }
    if (!panel.current?.animate || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { arrive(); return; }
    setChanging(true);
    const animation = panel.current.animate([
      { opacity: 1, transform: 'translateY(0)' },
      { opacity: 0, transform: `translateY(${backwards ? 12 : -12}px)` },
    ], { duration: 140, easing: 'ease-in', fill: 'forwards' });
    transition.current = animation;
    void animation.finished.then(() => {
      transition.current = null;
      if (alive.current) arrive();
    }).catch(() => { transition.current = null; if (alive.current) setChanging(false); });
  }
  function exit() { alive.current = false; if (preview) router.replace('/profile'); else { signOut(); router.replace('/'); } }

  async function save(fields: Record<string, unknown>, next: Step, finish = false) {
    if (lock.current || !token || !latest.current || conflict) return;
    if (preview) { if (finish) router.replace('/profile'); else go(next); return; }
    lock.current = true; setBusy(true); setError('');
    const body = JSON.stringify({ expected_version: latest.current.version, ...fields });
    if (!pending.current || pending.current.signature !== body) pending.current = { signature: body, key: crypto.randomUUID() };
    try {
      const saved = await profileApi<Profile>(finish ? '/onboarding/complete' : '', {
        method: finish ? 'POST' : 'PATCH', body,
        ...(finish ? { headers: { 'Idempotency-Key': pending.current.key } } : {}),
      }, token);
      if (!alive.current || !setProfile(saved)) return;
      latest.current = saved; pending.current = null;
      setSaveNote('Progress saved to your account.');
      if (!finish) go(next);
      // The shared guard routes only after server-confirmed completion.
    } catch (e) {
      if (!alive.current) return;
      if (finish && (!(e instanceof ApiError) || e.status >= 500)) {
        try { const saved = await profileApi<Profile>('', {}, token);
          if (!alive.current) return;
          if (saved.onboarding_complete && setProfile(saved)) return;
        } catch { /* Keep draft and request key for an uncertain completion retry. */ }
      }
      if (!alive.current) return;
      setConflict(e instanceof ApiError && e.status === 409);
      setError(e instanceof Error ? e.message : 'Your answer could not be saved. Please retry.');
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function reconcile() {
    if (!token || lock.current) return;
    lock.current = true; setBusy(true);
    try {
      const saved = await profileApi<Profile>('', {}, token);
      if (alive.current && setProfile(saved)) {
        latest.current = saved; setConflict(false); setError('');
        setSaveNote('Latest saved version loaded. Your draft is retained; review before saving.');
      }
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function chooseStatus(value: OccupationalStatus) {
    setStatus(value); setNoPrevious(false); if (value === 'unemployed' && status !== value) setPreviouslyEmployed(null);
    if (value === 'student' && !category) { setSaveNote('Your status and education path will be saved together.'); go('pathway'); }
    else void save({ occupational_status: value, no_previous_education: false }, value === 'employed' ? 'employer' : value === 'unemployed' ? 'previous' : 'pathway');
  }
  function choosePath(value: SchoolCategory) {
    setCategory(value); setNoPrevious(false); setCustom(false);
    if (value !== category) setEditor(editorFrom({}));
    void save({ occupational_status: status, school_category: value, no_previous_education: false }, 'school');
  }
  function educationDraft(value = editor): EducationDraft {
    return { institution: value.custom ? { kind: 'custom', name: value.institutionName.trim(), country_code: category === 'university' ? country || null : 'SG' } : value.institution,
      ...(needsGraduation && value.graduation ? { graduation_year: graduationYear(value.graduation) } : {}),
      course: value.noCourse || !value.course.trim() ? null : value.course.trim(),
      ...(student && value.year && value.yearCategory === category ? { study_year: Number(value.year) } : {}) };
  }
  function saveEducation(value: EducationEditor, next: Step) {
    setEditor(value);
    // Retained education in a new context is confirmed as a whole on the review screen.
    if (reviewRequired) {
      setSaveNote('Review your changed education before saving these answers.'); go(next); return;
    }
    try { void save({ education: educationDraft(value) }, next); } catch (error) { setError((error as Error).message); }
  }
  function submitSchool(event: FormEvent) {
    event.preventDefault();
    if (!editor.institutionName.trim()) { setError('Enter your school’s name or choose a search result.'); return; }
    saveEducation({ ...editor, custom: true }, afterSchool);
  }
  function submitCourse(event: FormEvent) {
    event.preventDefault(); saveEducation(editor, student ? 'year' : 'review');
  }
  function submitYear(event: FormEvent) {
    event.preventDefault();
    if (!/^[1-9]\d*$/.test(editor.year) || !Number.isSafeInteger(Number(editor.year))) { setError('Enter a positive whole study year.'); return; }
    saveEducation({ ...editor, yearCategory: category || null }, 'review');
  }
  const titles: Record<Step, string> = { status: 'Where are you right now?', previous: 'Have you worked before?', employer: status === 'unemployed' ? 'Where did you last work?' : 'Where do you work?', role: status === 'unemployed' ? 'What was your last role?' : 'What is your role?', industry: status === 'unemployed' ? 'Which industry did you work in?' : 'Which industry do you work in?', pathway: student ? 'Choose your education path.' : 'Your last education path.', school: questions.institution,
    graduation: 'When did you graduate?', course: questions.course, year: 'Which year are you in?', review: 'Your next chapter starts here.' };
  const descriptions: Record<Step, string> = { status: 'Every journey has a starting point. Let’s find yours.', previous: 'Your past experience helps us understand your starting point.', employer: 'Search for an organisation, or type its name if it isn’t listed.', role: 'Tell us the role you held at this organisation.', industry: 'Choose a suggestion, or enter your industry in your own words.', pathway: 'Choose a path, then we’ll help you find your school.',
    school: category === 'university' ? 'Search by name. Refine by country if you need to.' : 'Search for your school in Singapore, or add it yourself.',
    graduation: 'Tell us the year you graduated from this school. This helps put your education in context.',
    course: 'Your programme helps us understand your foundation. No named course? You can skip this.',
    year: 'Choose your current level. This helps put your experience in context.', review: 'Take a moment to check your details. You can always update them in My profile.' };
  const yearCount = category === 'secondary' ? 5 : category === 'junior_college' ? 3 : category === 'university' ? 5 : 3;
  return <div className="onboarding">
    <header className="onboarding-header">
      <div className="brand"><BrandLogo/></div>
      <span className="onboarding-header-note"><span className="onboarding-dot"/> A path that starts with you</span>
      <button type="button" className="onboarding-exit" onClick={exit} aria-label={preview ? "Exit preview" : "Exit setup and sign out"} title={preview ? "Return to profile" : "Exit setup and sign out"}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
    </header>
    <div className="onboarding-body">
      <main className="onboarding-main" id="main-content">
        <section key={step} ref={panel} className="onboarding-question" data-direction={direction} aria-labelledby="setup-question">
          {preview && <p className="onboarding-preview-note">Development preview · Answers are not saved</p>}
          <div className="onboarding-step-tag"><span className="onboarding-dot"/>{labels[step]}</div>
          <h1 id="setup-question" ref={heading} tabIndex={-1}>{titles[step]}</h1>
          <p className="onboarding-description">{descriptions[step]}</p>
          <fieldset disabled={busy || conflict || changing} className="onboarding-fields" aria-label={labels[step]}>
            {step === 'status' && <div className="onboarding-choices">{statuses.map((s, i) => <button type="button" className={`onboarding-choice ${status === s.id ? 'chosen' : ''}`} key={s.id} aria-label={s.label} onClick={() => chooseStatus(s.id)}><span className="onboarding-choice-icon" aria-hidden="true">{['01', '02', '03', '04'][i]}</span><span><strong>{s.label}</strong><small>{statusNotes[s.id]}</small></span><span className="onboarding-arrow" aria-hidden="true">↗</span></button>)}</div>}
            {step === 'previous' && <div className="onboarding-choices">{[true, false].map(answer => <button type="button" key={String(answer)} className="onboarding-choice" onClick={() => { setPreviouslyEmployed(answer); void save({ previously_employed: answer }, answer ? 'employer' : 'pathway'); }}><strong>{answer ? 'Yes, I have' : 'No, not yet'}</strong><span aria-hidden="true">→</span></button>)}</div>}
            {step === 'employer' && <form onSubmit={e => { e.preventDefault(); if (employer.trim()) void save({ employment: { employer: employer.trim() } }, 'role'); }}>
              <EmploymentSuggestions id="setup-employer" kind="companies" label={status === 'unemployed' ? 'Previous employer' : 'Place of employment'} value={employer} onChange={setEmployer} />
              <button type="submit" className="onboarding-continue" disabled={!employer.trim()}>Continue <span aria-hidden="true">→</span></button>
            </form>}
            {step === 'role' && <form onSubmit={e => { e.preventDefault(); if (role.trim()) void save({ employment: { role: role.trim() } }, 'industry'); }}>
              <div className="onboarding-answer-context">{employer}</div><label htmlFor="setup-role">Role</label><input id="setup-role" type="text" maxLength={300} value={role} placeholder="e.g. Business analyst" onChange={e => setRole(e.target.value)} />
              <button type="submit" className="onboarding-continue" disabled={!role.trim()}>Continue <span aria-hidden="true">→</span></button>
            </form>}
            {step === 'industry' && <form onSubmit={e => { e.preventDefault(); if (industry.trim()) void save({ employment: { industry: industry.trim() } }, 'pathway'); }}>
              <EmploymentSuggestions id="setup-industry" kind="industries" label="Industry" value={industry} onChange={setIndustry} />
              <button type="submit" className="onboarding-continue" disabled={!industry.trim()}>Continue <span aria-hidden="true">→</span></button>
            </form>}
            {step === 'pathway'  && <div className="onboarding-paths">{categories.map(c => <button type="button" key={c.id} aria-label={c.label} className={`onboarding-choice ${category === c.id && !noPrevious ? 'chosen' : ''}`} onClick={() => choosePath(c.id)}><span><strong>{c.label}</strong><small>{pathwayNotes[c.id]}</small></span><span className="onboarding-arrow" aria-hidden="true">→</span></button>)}
              {!student && <button type="button" className="onboarding-skip" onClick={() => { setNoPrevious(true); setCategory(''); void save({ occupational_status: status, school_category: null, no_previous_education: true }, 'review'); }}>No applicable previous education</button>}
              {categories.length === 0 && <p role="alert">Education paths are unavailable. Reload to try again, or exit and return later.</p>}
            </div>}
            {step === 'school' && <>
              <div className="onboarding-selected-path"><span>{categories.find(c => c.id === category)?.label}</span><button type="button" onClick={() => go('pathway')}>Change path</button></div>
              {!custom && category && <SchoolBrowser key={category} category={category} initialCountry={country} onCountryChange={setCountry} onSelect={school => {
                setCountry(school.country_code);
                saveEducation({ ...editor, institution: { kind: 'catalogue', id: school.id }, institutionName: school.name, custom: false }, afterSchool);
              }}/>}
              {!custom && editor.institutionName && <div className="onboarding-saved-school"><p>Previously saved school</p><button type="button" className="onboarding-choice" onClick={() => saveEducation(editor, afterSchool)}>{editor.institutionName}</button></div>}
              <button type="button" className="onboarding-skip" onClick={() => setCustom(value => !value)}>{custom ? 'Back to school search' : 'My school isn’t listed'}</button>
              {custom && <form onSubmit={submitSchool}><label htmlFor="setup-school">School name</label><input id="setup-school" type="text" autoFocus maxLength={300} value={editor.institutionName} onChange={e => setEditor({ ...editor, institutionName: e.target.value, custom: true })}/><button type="submit" className="onboarding-continue" disabled={!editor.institutionName.trim()}>Continue <span aria-hidden="true">→</span></button></form>}
              {category === 'university' && !custom && <p className="onboarding-country-note">The suggested country uses your browser settings. You can change it or choose all countries.</p>}
            </>}
            {step === 'graduation' && <form onSubmit={e => {
              e.preventDefault();
              try { graduationYear(editor.graduation); saveEducation(editor, 'course'); } catch (error) { setError((error as Error).message); }
            }}>
              <div className="onboarding-answer-context">{editor.institutionName}</div>
              <label htmlFor="setup-graduation">Year of graduation</label><input id="setup-graduation" type="number" min="1900" step="1" placeholder="e.g. 2024" value={editor.graduation} onChange={e => setEditor({ ...editor, graduation: e.target.value })}/>
              <button type="submit" className="onboarding-continue" disabled={!editor.graduation}>Continue <span aria-hidden="true">→</span></button>
            </form>}
            {step === 'course'  && <form onSubmit={submitCourse}>
              <div className="onboarding-answer-context">{editor.institutionName}</div>
              <label htmlFor="setup-course">{questions.course}</label><input id="setup-course" type="text" maxLength={300} placeholder="e.g. Computing & Design" value={editor.course} onChange={e => setEditor({ ...editor, course: e.target.value, noCourse: false })}/>
              <button type="submit" className="onboarding-continue" disabled={!editor.course.trim()}>Continue <span aria-hidden="true">→</span></button>
              <button type="button" className="onboarding-skip" onClick={() => saveEducation({ ...editor, course: '', noCourse: true }, student ? 'year' : 'review')}>No applicable named course / Skip</button>
            </form>}
            {step === 'year' && <form onSubmit={submitYear}>
              <div className="onboarding-year-choices">{Array.from({ length: yearCount }, (_, i) => i + 1).map(year => <button type="button" key={year} aria-pressed={editor.year === String(year)} onClick={() => setEditor({ ...editor, year: String(year), yearCategory: category || null })}>{studyYearLabel(category, year)}</button>)}</div>
              <label htmlFor="setup-year">Current study level/year</label><input id="setup-year" type="number" min="1" step="1" value={editor.year} onChange={e => setEditor({ ...editor, year: e.target.value, yearCategory: category || null })}/>
              <p className="onboarding-country-note">You can enter another year, including years beyond the options above.</p>
              <button type="submit" className="onboarding-continue" disabled={!editor.year}>Continue <span aria-hidden="true">→</span></button>
            </form>}
            {step === 'review' && <div className="onboarding-review">
              <div className="onboarding-review-badge" aria-hidden="true">↗</div>
              <dl>
                <div><dt>Status</dt><dd>{statuses.find(s => s.id === status)?.label}</dd><button type="button" onClick={() => go('status')}>Edit status</button></div>
                {status === 'unemployed' && <div><dt>Previously employed</dt><dd>{previouslyEmployed ? 'Yes' : 'No'}</dd><button type="button" onClick={() => go('previous')}>Edit work history</button></div>}
                {hasWork && <><div><dt>{status === 'unemployed' ? 'Previous employer' : 'Employer'}</dt><dd>{employer}</dd><button type="button" onClick={() => go('employer')}>Edit employer</button></div><div><dt>Role</dt><dd>{role}</dd><button type="button" onClick={() => go('role')}>Edit role</button></div><div><dt>Industry</dt><dd>{industry}</dd><button type="button" onClick={() => go('industry')}>Edit industry</button></div></>}
                <div><dt>Education path</dt><dd>{noPrevious ? 'No applicable previous education' : categories.find(c => c.id === category)?.label}</dd><button type="button" onClick={() => go('pathway')}>Edit education path</button></div>
                {!noPrevious && <><div><dt>School</dt><dd>{editor.institutionName}</dd><button type="button" onClick={() => go('school')}>Edit school</button></div>
                  {needsGraduation && <div><dt>Graduated</dt><dd>{editor.graduation}</dd><button type="button" onClick={() => go('graduation')}>Edit graduation year</button></div>}
                  <div><dt>Course</dt><dd>{editor.course || 'No named course'}</dd><button type="button" onClick={() => go('course')}>Edit course</button></div>
                  {student && <div><dt>Study year</dt><dd>{studyYearLabel(category, Number(editor.year))}</dd><button type="button" onClick={() => go('year')}>Edit study year</button></div>}</>}
              </dl>
              {reviewRequired && !noPrevious && <label className="onboarding-confirm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>I have reviewed these education details for my selected status and path.</label>}
              <button type="button" className="onboarding-continue" disabled={reviewRequired && !noPrevious && !confirmed} onClick={() => void save({ occupational_status: status, school_category: noPrevious ? null : category, no_previous_education: noPrevious,
                ...(status === 'unemployed' ? { previously_employed: previouslyEmployed } : {}),
                ...(hasWork ? { employment: { employer: employer.trim(), role: role.trim(), industry: industry.trim() } } : {}),
                ...(!noPrevious ? { education: educationDraft(), confirm_education_context: true } : {}) }, 'review', true)}>{preview ? 'Finish preview' : 'Enter Coachify'} <span aria-hidden="true">→</span></button>
            </div>}
          </fieldset>
          {busy && <p role="status" className="onboarding-saving">Saving your answer…</p>}
          {error && <div role="alert" className="error">{error} Your answer is retained.{conflict && <button type="button" disabled={busy} onClick={() => void reconcile()}>Load latest version and keep my draft</button>}</div>}
          {step !== 'status' && <button type="button" className="onboarding-back" disabled={busy || changing} onClick={() => go(steps[Math.max(0, index - 1)])}>← Back</button>}
        </section>
      </main>
    </div>
    <footer className="onboarding-footer" aria-label="Setup progress">
      <div className="onboarding-footer-inner">
        <div className="onboarding-progress-caption"><span>STEP {String(index + 1).padStart(2, '0')} <span className="muted">OF {String(steps.length).padStart(2, '0')}</span></span><strong>{labels[step]}</strong></div>
        <div className="onboarding-progress" role="progressbar" aria-label="Setup progress" aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={index + 1} aria-valuetext={`Step ${index + 1} of ${steps.length}: ${labels[step]}`}><span style={{ width: `${(index + 1) / steps.length * 100}%` }}/></div>
        <div className="onboarding-progress-note"><span className="onboarding-dot"/><p aria-live="polite">{preview ? "Preview only — your saved profile stays unchanged." : saveNote}</p></div>
      </div>
    </footer>
  </div>;
}
