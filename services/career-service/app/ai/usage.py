"""Per-user rolling completed usage. No maximum-output reservations."""
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

MAX_INPUT_TOKENS=4000
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
            with self.lock:self.local[key]=[v for v in self.local.get(key,[]) if v['at']>cutoff]+[entry]
        else:
            # Pipeline updates serialize appends across replicas; no read/replace race.
            pipeline=[{'$set':{
                'entries':{'$concatArrays':[{'$filter':{'input':{'$ifNull':['$entries',[]]},'as':'entry','cond':{'$gt':['$$entry.at',cutoff]}}},[entry]]},
                'expires_at':stamp+timedelta(seconds=61)}}]
            try:self.rows.update_one({'_id':key},pipeline,upsert=True)
            except DuplicateKeyError:self.rows.update_one({'_id':key},pipeline)
