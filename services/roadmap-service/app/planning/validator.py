"""Deterministic checks on an outline's milestones and gaps. Every problem found is returned for a bounded retry.

A material unknown marked for a diagnostic is satisfied here by that intent; the first planned week must contain the diagnostic task.
"""

def issue(code,message):
    return {'code':code,'message':message}

def assessment_lookup(assessment):
    outcomes={o['ref']:o for name in ('job_skill_gaps','interview_prep_gaps') for o in assessment[name]}
    conditions={o['ref'] for o in assessment.get('constraints',[])}
    satisfied={ref for group in assessment.get('groups',[]) if group.get('operator')=='any' and group.get('match_status')=='supported'
        for ref in group.get('requirement_refs',[])}
    return outcomes,conditions,satisfied

def check_milestones(draft,capacity,completed,retained):
    errors=[];keys=[m.key for m in draft.milestones];lookup={m.key:m for m in draft.milestones}
    for key in sorted({k for k in keys if keys.count(k)>1}):errors.append(issue('duplicate_milestone',f"Milestone key '{key}' is used more than once."))
    finished={}
    for session in completed:finished[session['milestone_key']]=finished.get(session['milestone_key'],0)+session['duration_minutes']
    for key in retained:
        if key not in lookup:errors.append(issue('completed_milestone_dropped',f"Milestone '{key}' has completed sessions and must stay in the plan."))
    for milestone in draft.milestones:
        label=f"Milestone '{milestone.key}'"
        if milestone.projected_end<milestone.projected_start:errors.append(issue('milestone_window_invalid',f'{label} ends before it starts.'))
        if capacity.target and milestone.projected_end>capacity.target:errors.append(issue('milestone_after_target',f'{label} ends after the target date {capacity.target}. List that work in beyond_deadline instead.'))
        marks=[c.key for c in milestone.checkpoints]
        for key in sorted({k for k in marks if marks.count(k)>1}):errors.append(issue('duplicate_checkpoint',f"{label} uses checkpoint key '{key}' more than once."))
        for checkpoint in milestone.checkpoints:
            if not milestone.projected_start<=checkpoint.date<=milestone.projected_end:errors.append(issue('checkpoint_outside_milestone',f"{label} has checkpoint '{checkpoint.key}' on {checkpoint.date}, outside its projected window."))
        if milestone.estimated_minutes==0 and milestone.key not in finished:errors.append(issue('milestone_effort_missing',f'{label} needs an estimated effort above zero.'))
        if milestone.key not in finished and milestone.projected_start<capacity.start:errors.append(issue('milestone_before_start',f'{label} starts before {capacity.start}.'))
        for prerequisite in milestone.prerequisite_keys:
            other=lookup.get(prerequisite)
            if not other:errors.append(issue('unknown_prerequisite',f"{label} references unknown prerequisite '{prerequisite}'."))
            elif other.projected_end>milestone.projected_end:errors.append(issue('prerequisite_order',f"{label} ends before its prerequisite '{prerequisite}' finishes."))
    state={}
    def visit(key):
        if state.get(key)=='open':return True
        if state.get(key)=='done' or key not in lookup:return False
        state[key]='open'
        cyclic=any(visit(next_key) for next_key in lookup[key].prerequisite_keys)
        state[key]='done'
        return cyclic
    if any(visit(key) for key in list(lookup)):errors.append(issue('prerequisite_cycle','Milestone prerequisites contain a cycle.'))
    # Test every window against the milestones wholly inside it.
    found=[]
    for first in sorted({m.projected_start for m in draft.milestones}):
        for last in sorted({m.projected_end for m in draft.milestones}):
            if last<first:continue
            inside=[m for m in draft.milestones if first<=m.projected_start and m.projected_end<=last]
            effort=sum(m.estimated_minutes for m in inside)
            available=capacity.between(first,last)
            if inside and effort>available:found.append((effort-available,first,last,effort,available,inside))
    for _,first,last,effort,available,inside in sorted(found,key=lambda row:-row[0])[:3]:
        names=', '.join(m.key for m in inside)
        errors.append(issue('milestone_capacity_exceeded',f'{names} need {effort} minutes between {first} and {last}, but only {available} usable minutes exist. Reduce scope or move work to beyond_deadline.'))
    return errors

def check_gaps(draft,assessment,confirmations,instruction,authorized_exclusions=(),uncovered_requirements=()):
    errors=[];outcomes,conditions,satisfied=assessment_lookup(assessment)
    ids=[g.id for g in draft.gaps];known=set(ids)
    for key in sorted({k for k in ids if ids.count(k)>1}):errors.append(issue('duplicate_gap',f"Gap id '{key}' is used more than once."))
    placed={g for m in draft.milestones for g in m.gap_ids}|{g for b in draft.beyond_deadline for g in b.gap_ids}
    for gap_id in sorted(placed-known):errors.append(issue('unknown_gap',f"Plan references unknown gap '{gap_id}'."))
    excluded=set()
    for exclusion in draft.exclusions:
        if exclusion.requirement_ref not in outcomes:errors.append(issue('unknown_requirement',f"Exclusion references unknown requirement '{exclusion.requirement_ref}'."))
        elif (exclusion.requirement_ref,exclusion.quote) not in authorized_exclusions and (not instruction or exclusion.quote not in instruction):errors.append(issue('exclusion_without_quote',f"Excluding '{exclusion.requirement_ref}' needs an exact quote from the user's current message."))
        else:excluded.add(exclusion.requirement_ref)
    for gap in draft.gaps:
        label=f"Gap '{gap.id}'";answer=(confirmations.get(gap.id) or {}).get('answer')
        if gap.source=='stated':
            if not gap.requirement_ref:errors.append(issue('requirement_label_mismatch',f'{label} is labelled stated but has no requirement reference.'))
            elif gap.requirement_ref in conditions:errors.append(issue('constraint_as_gap',f'{label} is a non-learning condition, which study cannot resolve.'))
            elif gap.requirement_ref not in outcomes:errors.append(issue('unknown_requirement',f"{label} references unknown requirement '{gap.requirement_ref}'."))
            else:
                outcome=outcomes[gap.requirement_ref]
                shortfall=any(c.get('status')=='confirmed_shortfall' for c in outcome.get('components',[]))
                if gap.requirement_ref in satisfied:errors.append(issue('supported_as_gap',f'{label} is covered by a supported alternative, so it is not a gap.'))
                elif outcome.get('match_status')=='supported' and answer!='no_experience':errors.append(issue('supported_as_gap',f'{label} is already supported by evidence, so it is not a gap.'))
                elif gap.status=='confirmed_gap' and not shortfall and answer!='no_experience':errors.append(issue('unknown_labelled_confirmed',f'{label} has no confirmed shortfall, so label it unknown.'))
                elif gap.status=='unknown' and shortfall and answer not in ('have_experience','some_experience'):errors.append(issue('shortfall_labelled_unknown',f'{label} has a confirmed shortfall, so label it confirmed_gap.'))
        else:
            if gap.requirement_ref:errors.append(issue('requirement_label_mismatch',f'{label} is labelled inferred but cites a stated requirement.'))
            if not (gap.inference_reason or '').strip():errors.append(issue('inference_unexplained',f'{label} is inferred and needs an inference_reason.'))
            if gap.status=='confirmed_gap' and answer!='no_experience':errors.append(issue('unknown_labelled_confirmed',f'{label} is an inferred requirement, so label it unknown.'))
        if gap.status=='confirmed_gap' and gap.id not in placed and gap.requirement_ref not in excluded:errors.append(issue('gap_not_placed',f'{label} is confirmed but is in no milestone or beyond_deadline entry.'))
        if gap.status=='unknown' and gap.plan_impact=='material' and not answer:
            if gap.resolution=='confirm_experience' and not (gap.confirmation_question or '').strip():errors.append(issue('unresolved_material_unknown',f'{label} needs a confirmation_question.'))
            elif not gap.resolution:errors.append(issue('unresolved_material_unknown',f'{label} could change the plan, so it needs a diagnostic or a confirmation question.'))
    by_ref={g.requirement_ref:g for g in draft.gaps if g.requirement_ref}
    for ref in assessment.get('priorities',[]):
        if ref in uncovered_requirements:continue  # Server-recorded partial coverage, shown before acceptance.
        gap=by_ref.get(ref)
        if ref not in excluded and (not gap or gap.id not in placed):errors.append(issue('priority_not_covered',f"Priority requirement '{ref}' must appear in a milestone or in beyond_deadline."))
    fits=draft.deadline_outcome.fits_in_runway
    if fits and draft.beyond_deadline:errors.append(issue('deadline_outcome_inconsistent','fits_in_runway is true, but work is listed beyond the deadline.'))
    if not fits and not draft.beyond_deadline:errors.append(issue('deadline_outcome_inconsistent','fits_in_runway is false, but no work is listed beyond the deadline.'))
    return errors
