"use client";
import Link from 'next/link';
import { useState } from 'react';
import { Icon } from '@/components/ui/icon';
import { PageTitle } from '@/components/ui/workspace-ui';
import { useProfile } from './profile-provider';
import { statuses, studyYearLabel } from './types';
import { ProfileForm } from './profile-form';

export function ProfileDashboard() {
  const { account, profile, developmentToolsEnabled } = useProfile();
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  function edit() { setSaved(false); setEditing(true); }
  if (!profile) return null;
  if (editing) return <ProfileForm onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setSaved(true); }} />;
  const student = profile.occupational_status === 'student';
  const employed = profile.occupational_status === 'employed';
  const previousWork = profile.occupational_status === 'unemployed' && profile.previously_employed === true;
  const noEducation = profile.no_previous_education && !student && !profile.school_category;
  const occupation = statuses.find(s => s.id === profile.occupational_status)?.label || 'Not added';
  const year = student && !profile.education_review_required && profile.current_study_year && profile.school_category
    ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
  return <section className="page on profile-dashboard">
    <PageTitle title="My profile"><button type="button" className="btn pri" onClick={edit}>Edit profile <span aria-hidden="true">↗</span></button></PageTitle>
    {saved && <p className="success" role="status">Profile updated.</p>}
    <div className="card profile-overview">
      <div className="profile-overview-avatar" aria-hidden="true"><Icon name="user" /></div>
      <div><p className="k">YOUR STARTING POINT</p><h2>{account?.name || 'Your profile'}</h2>{account?.email && <p className="small">{account.email}</p>}</div>
      <span className="profile-occupation-pill">{occupation}</span>
    </div>
    <div className="profile-summary-grid">
      <section className="card profile-summary" aria-labelledby="profile-background-title">
        <div className="profile-summary-title"><span className="profile-summary-icon"><Icon name="book" /></span><div><p className="k">01 / BACKGROUND</p><h2 id="profile-background-title">Your education</h2></div></div>
        <dl>
          <div><dt>Occupation</dt><dd>{occupation}</dd></div>
          <div><dt>{student ? 'Current place of education' : 'Place of last education'}</dt><dd>{noEducation ? 'No previous education' : profile.education.institution?.name || 'Not added'}</dd></div>
          <div><dt>{student ? 'Course of study' : 'Course studied'}</dt><dd>{noEducation ? 'Not applicable' : profile.education.course || 'No named course'}</dd></div>
          {!noEducation && profile.occupational_status === 'unemployed' && profile.previously_employed === false && <div><dt>Year of graduation</dt><dd>{profile.education.graduation_year || 'Not added'}{profile.education_review_required && profile.education.graduation_year ? ' · Needs review' : ''}</dd></div>}
          {student && <div><dt>Year of study</dt><dd>{year || 'Needs review'}</dd></div>}
        </dl>
        {profile.education_review_required && !noEducation && <p className="notice">Your saved education needs review for your current status. <button type="button" className="text-link profile-inline-link" onClick={edit}>Review details</button></p>}
      </section>
      {(employed || previousWork) && <section className="card profile-summary" aria-labelledby="profile-employment-title">
        <div className="profile-summary-title"><span className="profile-summary-icon employment"><Icon name="brief" /></span><div><p className="k">02 / WORK</p><h2 id="profile-employment-title">{previousWork ? 'Previous employment' : 'Current employment'}</h2></div></div>
        <dl><div><dt>{previousWork ? 'Previous employer' : 'Place of employment'}</dt><dd>{profile.employment?.employer || 'Not added'}</dd></div><div><dt>Role</dt><dd>{profile.employment?.role || 'Not added'}</dd></div><div><dt>Industry</dt><dd>{profile.employment?.industry || 'Not added'}</dd></div></dl>
        {(!profile.employment?.employer || !profile.employment?.role || !profile.employment?.industry) && <button type="button" className="text-link profile-add-work profile-inline-link" onClick={edit}>Add your employment details →</button>}
      </section>}
    </div>
    <div className="profile-preferences-link"><span>You can update your background and planning preferences whenever things change.</span><Link className="text-link" href="/profile/edit#planning-preferences">Planning preferences ↗</Link></div>
    {developmentToolsEnabled && <section className="profile-development" aria-label="Development tools"><div><span className="chip">Development</span><h3>Walk through the welcome experience.</h3><p>Preview every question again. Preview answers won’t change your saved profile.</p></div><Link className="btn ghost" href="/onboarding/preview">Preview onboarding <span aria-hidden="true">↗</span></Link></section>}
  </section>;
}
