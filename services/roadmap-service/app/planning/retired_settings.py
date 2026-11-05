"""Removes retired planner settings from saved records when the service starts.

New writes cannot contain these fields because PlannerConfig forbids them, so one pass over
existing records leaves none behind. It is safe to rerun. Workspace versions stay the same
because the fields never affected a plan, so open tabs do not need to reload.
"""
RETIRED=('buffer_percent','checkin_day','checkin_time')
OLD_BLACKOUTS='blackout_dates'
WORKSPACE_CONFIGS=('planner.config','planner.candidate.config','planner.active.config')
PLAN_CONFIGS=('config',)

def config_update(config,path):
    """The $set and $unset that clean one saved config, or nothing when it is already clean."""
    if not isinstance(config,dict):return {},{}
    unset={f'{path}.{field}':'' for field in (*RETIRED,OLD_BLACKOUTS) if field in config}
    replaced={}
    if OLD_BLACKOUTS in config and 'blackouts' not in config:
        replaced[f'{path}.blackouts']=[{'frequency':'once','start_date':day} for day in config[OLD_BLACKOUTS]]
    return replaced,unset

def nested(document,path):
    for part in path.split('.'):
        if not isinstance(document,dict):return None
        document=document.get(part)
    return document

def clean_collection(collection,paths):
    fields=[f'{path}.{field}' for path in paths for field in (*RETIRED,OLD_BLACKOUTS)]
    for document in collection.find({'$or':[{field:{'$exists':True}} for field in fields]},{path:1 for path in paths}):
        replaced,unset={},{}
        for path in paths:
            more,less=config_update(nested(document,path),path)
            replaced.update(more);unset.update(less)
        collection.update_one({'_id':document['_id']},{'$unset':unset,**({'$set':replaced} if replaced else {})})

def remove_retired_settings(store):
    if getattr(store,'rows',None) is None:return
    clean_collection(store.rows,WORKSPACE_CONFIGS)
    clean_collection(store.results_collection,PLAN_CONFIGS)
