"""Atomic Groq admission: in-flight allowances reconcile to actual completed usage."""
import hashlib
import json
import math
import threading
from datetime import timedelta
from uuid import uuid4
import tiktoken
from bson.codec_options import CodecOptions
from pymongo.errors import DuplicateKeyError
from app.repositories.goals import now

MAX_INPUT_TOKENS=6872
USER_TOKENS_PER_MINUTE=7000

def input_tokens(payload):
    content={key:payload[key] for key in ('messages','response_format','tools') if key in payload}
    text=json.dumps(content,ensure_ascii=False,separators=(',',':'))
    return len(tiktoken.get_encoding('o200k_harmony').encode(text,disallowed_special=()))

def consumed_tokens(raw,prompt_tokens):
    """Prefer consistent provider totals, including reasoning exactly once.

    Missing usage falls back to tokenized input plus observed answer/reasoning;
    never charge the maximum possible output allowance.
    """
    try:data=json.loads(raw)
    except (ValueError,TypeError):return prompt_tokens
    if not isinstance(data,dict):return prompt_tokens
    usage=data.get('usage')
    if isinstance(usage,dict):
        values=[usage.get(k) for k in ('prompt_tokens','completion_tokens','total_tokens')]
        if all(type(v) is int and v>=0 for v in values) and values[0]+values[1]==values[2]:return values[2]
    text=[]
    for choice in data.get('choices',[]) if isinstance(data.get('choices'),list) else []:
        message=choice.get('message',{}) if isinstance(choice,dict) else {}
        if isinstance(message,dict):text.extend(v for k in ('content','reasoning','reasoning_content') if isinstance(v:=message.get(k),str))
    return prompt_tokens+len(tiktoken.get_encoding('o200k_harmony').encode(' '.join(text),disallowed_special=()))

class UserQuotaExceeded(Exception):
    def __init__(self,retry_after):self.retry_after=retry_after

class UserTokenUsage:
    def __init__(self,database=None,clock=now):
        self.rows=database.with_options(codec_options=CodecOptions(tz_aware=True)).ai_user_usage if database is not None else None
        self.clock=clock;self.lock=threading.Lock();self.local={}
        if self.rows is not None:self.rows.create_index('expires_at',expireAfterSeconds=0)

    def key(self,owner):return hashlib.sha256(owner.encode()).hexdigest()

    def check(self,owner):
        stamp=self.clock();key=self.key(owner)
        if self.rows is None:
            with self.lock:entries=list(self.local.get(key,[]))
        else:entries=(self.rows.find_one({'_id':key}) or {}).get('entries',[])
        entries=sorted((v for v in entries if v['at']>stamp-timedelta(seconds=60)),key=lambda v:v['at'])
        used=sum(v['tokens'] for v in entries)
        if used<USER_TOKENS_PER_MINUTE:return
        for entry in entries:
            used-=entry['tokens']
            if used<USER_TOKENS_PER_MINUTE:
                raise UserQuotaExceeded(max(1,math.ceil((entry['at']+timedelta(seconds=60)-stamp).total_seconds())))

    def record(self,owner,tokens):
        if type(tokens) is not int or tokens<=0:return
        stamp=self.clock();key=self.key(owner)
        entry={'id':uuid4().hex,'at':stamp,'tokens':tokens}
        cutoff=stamp-timedelta(seconds=60)
        if self.rows is None:
            with self.lock:self.local[key]=[v for v in self.local.get(key,[]) if v.get('until',v['at']+timedelta(seconds=60))>stamp]+[entry]
        else:
            # Pipeline updates serialize appends across replicas; no read/replace race.
            pipeline=[{'$set':{
                'entries':{'$concatArrays':[{'$filter':{'input':{'$ifNull':['$entries',[]]},'as':'entry','cond':{'$or':[{'$gt':['$$entry.at',cutoff]},{'$gt':['$$entry.until',stamp]}]}}},[entry]]},
                'expires_at':stamp+timedelta(seconds=121)}}]
            try:self.rows.update_one({'_id':key},pipeline,upsert=True)
            except DuplicateKeyError:self.rows.update_one({'_id':key},pipeline)

    def reserve(self,owner,prompt,output):
        """Reserve a complete call atomically, including across service replicas.

        Reservations are temporary capacity, never billed usage. Unused output is
        released on completion. An expired worker lease conservatively counts as
        spent for one more minute, preventing a crash from erasing paid usage.
        """
        key=self.key(owner)
        for _ in range(100):
            with self.lock:
                stamp=self.clock()
                row=(self.rows.find_one({'_id':key}) or {}) if self.rows is not None else {'entries':self.local.get(key,[])}
                entries=[v for v in row.get('entries',[]) if v.get('until',v['at']+timedelta(seconds=60))>stamp]
                used=sum(v['tokens'] for v in entries)
                needed=prompt+output
                if used+needed>USER_TOKENS_PER_MINUTE:
                    for entry in sorted(entries,key=lambda v:v.get('until',v['at']+timedelta(seconds=60))):
                        used-=entry['tokens']
                        if used+needed<=USER_TOKENS_PER_MINUTE:
                            delay=(entry.get('until',entry['at']+timedelta(seconds=60))-stamp).total_seconds()
                            raise UserQuotaExceeded(max(1,min(60,math.ceil(delay))))
                    raise UserQuotaExceeded(60)
                ticket=uuid4().hex
                entries.append({'id':ticket,'at':stamp,'tokens':needed,'reserved':True,'until':stamp+timedelta(seconds=120)})
                if self.rows is None:
                    self.local[key]=entries
                    return ticket
                # Compare the entire ledger so concurrent record() calls cannot be lost.
                try:
                    changed=self.rows.update_one({'_id':key,'entries':row.get('entries',{'$exists':False})},
                        {'$set':{'entries':entries,'expires_at':stamp+timedelta(seconds=121)}},upsert=not bool(row))
                except DuplicateKeyError:continue
                if changed.matched_count or changed.upserted_id:return ticket
        raise UserQuotaExceeded(1)

    def settle(self,owner,ticket,tokens):
        stamp=self.clock();key=self.key(owner)
        entry={'id':ticket,'at':stamp,'tokens':max(0,tokens)}
        if self.rows is None:
            with self.lock:self.local[key]=[entry if v['id']==ticket else v for v in self.local.get(key,[])]
        else:
            self.rows.update_one({'_id':key,'entries.id':ticket},[{'$set':{
                'entries':{'$map':{'input':'$entries','as':'entry','in':{'$cond':[{'$eq':['$$entry.id',ticket]},entry,'$$entry']}}}}}])
