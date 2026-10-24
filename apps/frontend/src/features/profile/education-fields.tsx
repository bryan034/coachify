"use client";
import type { Education, EducationDraft, InstitutionInput, OccupationalStatus, SchoolCategory } from './types';
import { educationQuestions, studyYearLabel } from './types';

export type EducationEditor = {
  institution: InstitutionInput | undefined; institutionName: string; custom: boolean;
  course: string; courseDirty: boolean; noCourse: boolean;
  year: string; yearDirty: boolean; yearCategory?: SchoolCategory | null; yearLabel?: string | null;
};
export function editorFrom(education: Education): EducationEditor {
  const school = education.institution;
  return { institution: school ? (school.kind === 'catalogue' ? { kind: 'catalogue', id: school.id! }
    : { kind: 'custom', name: school.name, country_code: school.country_code }) : undefined,
    institutionName: school?.name || '', custom: school?.kind === 'custom',
    course: education.course || '', courseDirty: false, noCourse: false,
    year: education.study_year == null ? '' : String(education.study_year), yearDirty: false, yearCategory: education.study_year_category, yearLabel: education.study_year_label };
}
export function educationPayload(editor: EducationEditor, dirtyInstitution: boolean, status: OccupationalStatus): EducationDraft {
  const draft: EducationDraft = {};
  if (dirtyInstitution) draft.institution = editor.custom
    ? { kind: 'custom', name: editor.institutionName } : editor.institution;
  if (editor.courseDirty) draft.course = editor.noCourse ? null : editor.course;
  if (editor.yearDirty && status === 'student') {
    if (!/^[1-9]\d*$/.test(editor.year) || !Number.isSafeInteger(Number(editor.year))) {
      throw new Error('Study year must be a positive whole number.');
    }
    draft.study_year = Number(editor.year);
  }
  return draft;
}
export function EducationFields({ status, category, editor, setEditor, onInstitutionDirty }: {
  status: OccupationalStatus; category: SchoolCategory | ''; editor: EducationEditor;
  setEditor: (next: EducationEditor) => void;
  onInstitutionDirty: () => void;
}) {
  const questions = educationQuestions(status);
  return <section className="education-fields" aria-label="Education details">
    <h2>Your education</h2>
    <label><input type="checkbox" checked={editor.custom} onChange={event => {
      setEditor({ ...editor, custom: event.target.checked, institutionName: '', institution: event.target.checked ? undefined : null });
      onInstitutionDirty();
    }} />My institution is not listed</label>
    {editor.custom ? <label>Institution name<input type="text" maxLength={300} value={editor.institutionName}
      onChange={event => { setEditor({ ...editor, institutionName: event.target.value }); onInstitutionDirty(); }} /></label>
      : <p>Selected institution: <strong>{editor.institutionName || 'None selected'}</strong></p>}
    {status !== 'student' && <button type="button" onClick={() => {
      setEditor({ ...editor, institution: null, institutionName: '', custom: false }); onInstitutionDirty();
    }}>Clear institution</button>}
    <label>{questions.course}<input type="text" maxLength={300} value={editor.course}
      disabled={editor.noCourse} onChange={event => setEditor({ ...editor, course: event.target.value, courseDirty: true, noCourse: false })} /></label>
    <label><input type="checkbox" checked={editor.noCourse}
      onChange={event => setEditor({ ...editor, noCourse: event.target.checked, courseDirty: true })} />No applicable named course/programme</label>
    {questions.showYear ? <label>Current study level/year<input type="number" min="1" step="1" value={editor.year}
      onChange={event => setEditor({ ...editor, year: event.target.value, yearDirty: true })} />
      <span className="muted">{editor.year && !editor.yearDirty && editor.yearCategory && editor.yearCategory !== category ? `Previously declared ${editor.yearLabel || editor.year}. Enter the year for the new category before confirming.` : editor.year && /^[1-9]\d*$/.test(editor.year) ? studyYearLabel(category, Number(editor.year)) : 'Enter your current year, including years beyond 4 if applicable.'}</span></label>
      : editor.year && <p className="muted">Previous study year retained: {editor.year}. It is not treated as your current study year.</p>}
  </section>;
}
