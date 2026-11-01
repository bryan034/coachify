"""Keep independently valid Discovery sections; repairs cannot replace accepted data.

Only complete JSON objects enter this collector. It never repairs JSON text, unwraps
unknown envelopes, or treats schema conformance as evidence of semantic correctness.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import get_args, get_origin

from pydantic import TypeAdapter, ValidationError

from app.schemas.discovery import ConversationMemory, DiscoveryUnderstanding, recent_texts

MISSING=object()
MAX_SECTION_RETRIES=2


@dataclass
class Section:
    path: tuple
    adapter: TypeAdapter
    schema: dict
    recent_limit: int | None = None

    @property
    def key(self):return '.'.join(map(str,self.path))


class DiscoverySections:
    def __init__(self,model,stage,context):
        self.model,self.stage,self.context=model,stage,context
        self.schema=model.model_json_schema()
        previous=context.get('previous') or {}
        self.baseline={}
        if stage=='discovery_turn':
            self.baseline={**previous,'action':'ANSWER','scope':context.get('scope'),'question':None,
                'reply':'I could not complete part of that answer. Please tell me more about your career question.',
                'memory':context.get('memory',{}),'understanding':context.get('understanding',{}),
                'source_ids':[],'recommendations':[]}
        elif stage=='discovery_plan':self.baseline={'related_roles':[],'queries':[]}
        elif stage=='discovery_assess':self.baseline={'sources':[]}
        elif stage=='discovery_extract':self.baseline={'listings':[],'question':None,'question_refs':[]}
        elif stage=='discovery_summary':self.baseline={'skills':[],'responsibility_refs':[],'specialisations':[],'question':None}
        self.values={};self.pending={};self.sections={};self.collections={}

    def _fields(self,model,data,prefix=(),schema=None):
        schema=schema or model.model_json_schema()
        for name,field in model.model_fields.items():
            path=(*prefix,name);raw=data.get(name,MISSING)
            item_schema=schema['properties'][name]
            if not prefix and name in ('memory','understanding') and raw is not MISSING and isinstance(raw,dict):
                nested=ConversationMemory if name=='memory' else DiscoveryUnderstanding
                self._fields(nested,raw,path)
                continue
            annotation=field.rebuild_annotation()
            limit=(3 if name=='open_questions' else 6) if model==ConversationMemory else 60 if name=='excluded_skills' else 30 if name=='requested_skills' else None
            # Research items are sections too: one bad listing/skill does not
            # discard all other items in the response. Collection size stays bounded.
            args=get_args(field.annotation)
            if (get_origin(field.annotation)==list and args and hasattr(args[0],'model_fields')
                and isinstance(raw,list) and len(raw)<=item_schema.get('maxItems',len(raw))):
                self.collections[path]=len(raw)
                for index,value in enumerate(raw):
                    self._section(Section((*path,index),TypeAdapter(args[0]),item_schema['items']),value)
                if not raw:self.values[path]=[]
                continue
            section=Section(path,TypeAdapter(annotation),item_schema,limit)
            if raw is MISSING and not field.is_required() and not (self.stage=='discovery_extract' and name=='question_refs' and data.get('question')):
                # Omitted optional updates preserve existing state rather than
                # implicitly clearing remembered interests or skill edits.
                continue
            self._section(section,raw)

    def _section(self,section,raw):
        key=section.key;self.sections[key]=section
        try:
            if raw is MISSING:raise ValueError('missing')
            if section.recent_limit:raw=recent_texts(raw,section.recent_limit)
            value=section.adapter.validate_python(raw)
            self._semantic(section.path,value)
        except (ValidationError,ValueError,TypeError,IndexError):
            self.pending[key]=section
        else:
            self.values[section.path]=value
            self.pending.pop(key,None)

    def _semantic(self,path,value):
        name=path[0];sources=self.context.get('sources',[])
        if len(path)==1 and isinstance(value,list) and value and hasattr(value[0],'model_fields'):
            seen=set()
            for index,item in enumerate(value):
                key=getattr(item,'ref',getattr(item,'name',getattr(item,'area',None)))
                if isinstance(key,str):key=' '.join(key.casefold().split())
                if key in seen:raise ValueError('duplicate_item')
                seen.add(key)
                self._semantic((*path,index),item)
        if self.stage=='discovery_turn' and name=='source_ids':
            allowed={ref for fact in self.context.get('facts',[]) for ref in fact.get('source_ids',[])}
            if any(ref not in allowed for ref in value):raise ValueError('source_reference')
        if name in ('sources','listings') and len(path)==2:
            if not 0<=value.ref<len(sources):raise ValueError('source_reference')
            if any(other_path!=path and other_path[0]==name and getattr(other,'ref',None)==value.ref
                   for other_path,other in self.values.items()):raise ValueError('duplicate_reference')
            if name=='listings':
                source=sources[value.ref]
                if value.job_title not in (source.get('excerpt','')+' '+source.get('title','')):raise ValueError('job_title')
                if len(value.requirements)>self.context.get('max_requirements',15):raise ValueError('requirement_limit')
        if self.stage=='discovery_assess' and name=='sources' and len(path)==1 and len(value)!=len(sources):
            raise ValueError('missing_assessments')
        if self.stage=='discovery_extract' and name=='question_refs':
            if any(not 0<=ref<len(sources) for ref in value):raise ValueError('question_reference')
            if self.values.get(('question',)) and not value:raise ValueError('question_reference')
        if self.stage=='discovery_summary':
            if name=='responsibility_refs' and any(not 0<=ref<len(self.context.get('responsibilities',[])) for ref in value):raise ValueError('responsibility_reference')
            if name=='skills' and len(path)==2:
                if any(not 0<=ref<len(self.context.get('skills',[])) for ref in value.skill_refs):raise ValueError('skill_reference')
                if not value.skill_refs and value.name not in self.context.get('requested_skills',[]):raise ValueError('unsupported_skill')
                normal=lambda text:' '.join(text.casefold().split())
                excluded={normal(text) for text in self.context.get('excluded_skills',[])}
                if normal(value.name) in excluded:raise ValueError('excluded_skill')
                frequencies=self.context.get('frequencies',[])
                if any(ref<len(frequencies) and normal(frequencies[ref]['name']) in excluded for ref in value.skill_refs):raise ValueError('excluded_skill')
                if any(other_path!=path and other_path[0]=='skills' and normal(other.name)==normal(value.name)
                       for other_path,other in self.values.items()):raise ValueError('duplicate_skill')

    def initial(self,data):
        self._fields(self.model,data if isinstance(data,dict) else {})
        if self.stage=='discovery_assess' and ('sources',) in self.collections:
            from app.schemas.discovery import SourceAssessment
            path=('sources',);size=self.collections[path];expected=len(self.context.get('sources',[]))
            if size<expected:
                self.values.pop(path,None)
                self.collections[path]=expected
                for index in range(size,expected):
                    self._section(Section((*path,index),TypeAdapter(SourceAssessment),self.schema['properties']['sources']['items']),MISSING)

    def repair_schema(self):
        return {'type':'object','properties':{key:section.schema for key,section in self.pending.items()},
            'required':list(self.pending),'additionalProperties':False,'$defs':self.schema.get('$defs',{})}

    def repair(self,data):
        data=data if isinstance(data,dict) else {}
        for key,section in list(self.pending.items()):self._section(section,data.get(key,MISSING))

    @property
    def failures(self):return tuple(self.pending)

    def finish(self):
        data=deepcopy(self.baseline)
        for path,size in self.collections.items():
            data[path[0]]=[self.values[(*path,index)] for index in range(size) if (*path,index) in self.values]
        for path,value in self.values.items():
            if len(path)==1:data[path[0]]=value
            elif isinstance(path[1],str):data.setdefault(path[0],{})[path[1]]=value
        if self.stage=='discovery_turn':
            if data['action']=='REJECT_OUT_OF_SCOPE':
                return self.model.model_validate({**self.baseline,'action':'REJECT_OUT_OF_SCOPE'})
            if 'action' in self.pending:
                # Unclassified text cannot bypass the career-only boundary.
                data.update(action='ANSWER',reply=self.baseline['reply'],question=None,recommendations=[],source_ids=[])
            if 'source_ids' in self.pending:
                data.update(reply=self.baseline['reply'],question=None,source_ids=[])
            if self.pending:
                data['action']='ANSWER'
                data['scope']=self.context.get('scope')
        if self.stage=='discovery_assess':
            # Missing assessments stay rejected; they are never relabelled as
            # relevant to fill the sample. Valid assessments remain untouched.
            found={value.ref for value in data['sources']}
            data['sources']=[*data['sources'],*[{'ref':ref,'relevant':False,'score':0,'quote':None}
                for ref in range(len(self.context.get('sources',[]))) if ref not in found]]
        if self.stage=='discovery_extract' and not data.get('question_refs'):data['question']=None
        return self.model.model_validate(data)
