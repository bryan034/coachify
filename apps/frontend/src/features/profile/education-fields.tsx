"use client";
import type { Education, EducationDraft, InstitutionInput, OccupationalStatus, SchoolCategory } from './types';
import { educationQuestions, studyYearLabel } from './types';

export type EducationEditor = {
  institution: InstitutionInput | undefined; institutionName: string; custom: boolean;
  course: string; courseDirty: boolean; noCourse: boolean;
  graduation: string; graduationDirty: boolean;
  year: string; yearDirty: boolean; yearCategory?: SchoolCategory | null; yearLabel?: string | null;
};
export function editorFrom(education: Education): EducationEditor {
  const school = education.institution;
  return { institution: school ? (school.kind === 'catalogue' ? { kind: 'catalogue', id: school.id! }
    : { kind: 'custom', name: school.name, country_code: school.country_code }) : undefined,
    institutionName: school?.name || '', custom: school?.kind === 'custom',
    graduation: education.graduation_year == null ? '' : String(education.graduation_year), graduationDirty: false,
    course: education.course || '', courseDirty: false, noCourse: false,
    year: education.study_year == null ? '' : String(education.study_year), yearDirty: false, yearCategory: education.study_year_category, yearLabel: education.study_year_label };
}
export function graduationYear(value: string): number {
  const year = Number(value);
  const currentYear = Number(new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: 'Asia/Singapore' }).format(new Date()));
  if (!/^\d{4}$/.test(value) || year < 1900 || year > currentYear) throw new Error(`Enter a graduation year between 1900 and ${currentYear}.`);
  return year;
}
export function educationPayload(editor: EducationEditor, dirtyInstitution: boolean, status: OccupationalStatus): EducationDraft {
  const draft: EducationDraft = {};
  if (dirtyInstitution) draft.institution = editor.custom
    ? { kind: 'custom', name: editor.institutionName } : editor.institution;
  if (editor.graduationDirty) draft.graduation_year = editor.graduation ? graduationYear(editor.graduation) : null;
  if (editor.courseDirty) draft.course = editor.noCourse || !editor.course.trim() ? null : editor.course;
  if (editor.yearDirty && status === 'student') {
    if (!/^[1-9]\d*$/.test(editor.year) || !Number.isSafeInteger(Number(editor.year))) {
      throw new Error('Study year must be a positive whole number.');
    }
    draft.study_year = Number(editor.year);
  }
  return draft;
}
export function EducationFields({ status, category, editor, setEditor }: {
  status: OccupationalStatus; category: SchoolCategory | ''; editor: EducationEditor;
  setEditor: (next: EducationEditor) => void;
}) {
  const questions = educationQuestions(status);
  return <section className="education-fields" aria-label="Education details">
    <label>{questions.course}<input type="text" maxLength={300} placeholder="Course or programme (optional)" value={editor.course}
      onChange={event => setEditor({ ...editor, course: event.target.value, courseDirty: true, noCourse: false })} /></label>
    {questions.showYear ? <label>Current study level/year<input type="number" min="1" step="1" value={editor.year}
      onChange={event => setEditor({ ...editor, year: event.target.value, yearDirty: true })} />
      <span className="muted">{editor.year && !editor.yearDirty && editor.yearCategory && editor.yearCategory !== category ? `Previously declared ${editor.yearLabel || editor.year}. Enter the year for the new category before confirming.` : editor.year && /^[1-9]\d*$/.test(editor.year) ? studyYearLabel(category, Number(editor.year)) : 'Enter your current year, including years beyond 4 if applicable.'}</span></label>
      : null}
  </section>;
}
