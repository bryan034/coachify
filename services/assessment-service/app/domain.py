"""Component evidence validation and deterministic AND/OR outcomes."""
from elo_shared.runtime import Problem

def aggregate(statuses,operator='all'):
    if not statuses: return 'uncertain'
    if operator=='any':
        if 'supported' in statuses:return 'supported'
        if all(s=='confirmed_shortfall' for s in statuses):return 'confirmed_shortfall'
        if 'partial' in statuses:return 'partial'
        return 'uncertain'
    if all(s=='supported' for s in statuses):return 'supported'
    if 'supported' in statuses or 'partial' in statuses:return 'partial'
    if 'confirmed_shortfall' in statuses:return 'confirmed_shortfall'
    return 'uncertain'

def group_outcome(items,operator):
    statuses=[]
    for item in items:
        status=item['match_status']
        # A partially supported AND route can still contain a proven unmet condition.
        # It cannot satisfy an OR alternative merely because another component is supported.
        if operator=='any' and any(c['status']=='confirmed_shortfall' for c in item['components']):
            status='confirmed_shortfall'
        statuses.append(status)
    return aggregate(statuses,operator)

def validate_batch(output,requirements,evidence):
    expected={r['ref']:r for r in requirements}
    refs=[o.requirement_ref for o in output.outcomes]
    if len(refs)!=len(set(refs)) or set(refs)!=set(expected):raise Problem('The model did not assess every requested requirement exactly once.',502,'assessment_output')
    results=[]
    for outcome in output.outcomes:
        requirement=expected[outcome.requirement_ref]
        dimensions={c.dimension for c in outcome.components}
        required=set()
        if requirement.get('kind')=='job_skill':required.add('capability')
        if requirement.get('required_proficiency') is not None:required.add('proficiency')
        if requirement.get('required_experience_months') is not None or requirement.get('minimum_months') is not None or requirement.get('maximum_months') is not None:required.add('duration')
        if requirement.get('category')=='qualification' and requirement.get('kind')=='constraint':required.add('qualification')
        if not required<=dimensions:raise Problem('The assessment omitted a required scope component.',502,'assessment_output')
        for component in outcome.components:
            if len(component.evidence_refs)!=len(set(component.evidence_refs)) or any(ref not in evidence for ref in component.evidence_refs):
                raise Problem('The assessment referenced unavailable evidence.',502,'assessment_output')
            selected=[evidence[ref] for ref in component.evidence_refs]
            if component.status!='uncertain' and not selected:raise Problem('A supported or unmet condition needs relevant declared evidence.',502,'assessment_output')
            if component.status=='confirmed_shortfall':
                quote=component.limitation_quote
                if not quote or not any(quote in item['text'] for item in selected):raise Problem('A shortfall needs an exact explicit limitation from the supplied evidence.',502,'assessment_output')
            if component.status=='supported' and any(item.get('attribution') in ('team','observed','denied') for item in selected):
                raise Problem('Team-only or denied evidence cannot establish personal capability.',502,'assessment_output')
            if component.status=='supported' and component.dimension in ('capability','proficiency','duration','independence'):
                if any(item.get('unscoped_item') for item in selected):raise Problem('Use the source-scoped personal skill claim, not its whole team/project item.',502,'assessment_output')
                if all(item.get('support_uncertain') for item in selected):raise Problem('Uncertain support cannot establish a known capability attribute.',502,'assessment_output')
            if component.status=='supported' and component.dimension in ('proficiency','duration','independence'):
                if not component.support_quote or not any(component.support_quote in item['text'] for item in selected):raise Problem('Known capability attributes need an exact supporting declaration.',502,'assessment_output')
        if outcome.mapping_method=='canonical':
            canonical=requirement.get('canonical_skill_id')
            references={ref for c in outcome.components for ref in c.evidence_refs}
            if not canonical or not any(evidence[ref].get('canonical_skill_id')==canonical for ref in references):
                raise Problem('Canonical mapping must resolve to the same supplied registry identity.',502,'assessment_output')
        status=aggregate([c.status for c in outcome.components])
        results.append({**requirement, 'match_status':status,'components':[c.model_dump() for c in outcome.components],
            'recommendation':outcome.recommendation,'mapping_method':outcome.mapping_method,'mapping_reason':outcome.mapping_reason})
    return results

INSTRUCTIONS='''You are a careful career adviser assessing declared evidence against supplied requirements.
Assess every supplied requirement exactly once. Break conditions into relevant components: capability, proficiency, duration, independence, qualification or eligibility. A mere skill mention cannot establish duration, advanced proficiency or independent work. Missing/contradictory/skipped information is uncertain, never absence. Basic use is NOT an explicit inability to do advanced work. Confirm a shortfall only from an exact declared limitation quote establishing that specific unmet condition; return its exact quote and source refs. User declarations suffice without proof. Team-only/observed/denied sources cannot establish personal capability; preserve other independent sources. Personal contribution and assistance are source scoped. Dates of employment/project do not automatically establish time using every skill. Never sum overlapping periods. Profile status or school category does not imply skill, qualification or eligibility.
Use canonical matching where supplied identities agree. Otherwise explain contextual semantic relevance, leaving ambiguity unresolved; do not invent registry IDs. Propose recommendations, not mandatory work. Interview expectations are preparation advice, not employer JD requirements or proof of inability. Preserve origins, conditions and alternative scope. Every supported/shortfall component needs supplied evidence refs. For supported proficiency, duration or independence supply support_quote as an exact declaration establishing that attribute. Cover capability for each job skill and every stated proficiency/duration condition. Whole project/experience items are unscoped context: use their skill claims for personal capability, never bypass source-specific attribution. Repeated/attached descriptions do not create independent proof. Explain uncertainties specifically. Never manufacture an employer pass mark. Return the schema.'''
