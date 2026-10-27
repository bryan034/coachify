"""Resume unsupported model-provider waits without discarding checkpointed research work."""
from app.repositories.goals import now
from app.schemas.opportunity import CATEGORIES


def resume_obsolete_model_waits(rows,kind):
    stamp=now()
    if kind=='opportunity_job':
        eligible={'kind':kind,'status':'pending','finished':False,
            '$or':[{'worker_until':{'$exists':False}},{'worker_until':{'$lte':stamp}}],
            # Another category may still be waiting for Brave. Its real provider
            # cooldown must survive even if an earlier branch stored unsupported provider state.
            '$nor':[{f'categories.{category}.status':'pending',
                f'categories.{category}.error_code':'source_rate_limited'} for category in CATEGORIES]}
    elif kind=='career_discovery':
        eligible={'kind':kind,'status':'waiting','lease_until':{'$lte':stamp},'error_code':'rate_limited'}
    else:raise ValueError('Unsupported research job kind.')
    eligible['$and']=[{'$or':[{'provider':{'$exists':True,'$nin':['gemini','brave',None]}},{'provider':None,'limit_scope':'user'}]}]
    return rows.update_many(eligible,{'$set':{'next_attempt_at':stamp,'provider':None,
        'limit_scope':None,'updated_at':stamp}}).modified_count
