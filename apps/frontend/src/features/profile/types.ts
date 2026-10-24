export type OccupationalStatus = 'student' | 'national_service' | 'unemployed' | 'employed';
export type SchoolCategory = 'secondary' | 'ite' | 'polytechnic' | 'junior_college' | 'university';
export type Profile = {
  version: number; occupational_status: OccupationalStatus | null;
  school_category: SchoolCategory | null; education_context: 'current' | 'last' | null;
  education_review_required: boolean; education: Education; current_study_year?: number | null;
};
export type Category = { id: SchoolCategory; label: string };
export type Institution = { id: string; name: string; country: string; country_code: string };
export type SchoolResults = { items: Institution[]; total: number; offset: number; limit: number; snapshot_date: string; coverage_note: string };
export const statuses: { id: OccupationalStatus; label: string }[] = [
  { id: 'student', label: 'Student' }, { id: 'national_service', label: 'National Service' },
  { id: 'unemployed', label: 'Unemployed' }, { id: 'employed', label: 'Employed' },
];
export function educationQuestions(status: OccupationalStatus) {
  return status === 'student'
    ? { institution: 'Where are you studying?', course: 'What course are you studying?', showYear: true }
    : { institution: 'Where did you last study?', course: 'What course did you study?', showYear: false };
}

export type SavedInstitution = { kind: 'catalogue' | 'custom'; id: string | null; name: string; country_code: string | null; snapshot_date?: string | null };
export type InstitutionInput = { kind: 'catalogue'; id: string } | { kind: 'custom'; name: string; country_code?: string | null } | null;
export type Education = {
  institution?: SavedInstitution | null; course?: string | null; study_year?: number | null;
  study_year_label?: string | null; study_year_category?: SchoolCategory | null;
  category?: SchoolCategory | null; context?: 'current' | 'last' | null;
};
export type EducationDraft = { institution?: InstitutionInput; course?: string | null; study_year?: number };
export function studyYearLabel(category: SchoolCategory | '', year: number) {
  return `${category === 'secondary' ? 'Secondary' : category === 'junior_college' ? 'JC' : 'Year'} ${year}`;
}
