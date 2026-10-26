"""Small routing/answer contracts; never model-authored database queries."""
from typing import Literal
from pydantic import Field
from app.schemas.analysis import Contract,Text
from app.schemas.jd import ChatText

Topic=Literal['role','skills','requirements','interview_process','interview_skills','preparation','overview','edit','off_topic']
class QuestionRoute(Contract):
    topic:Topic
    terms:list[Text]=Field(default_factory=list,max_length=4)
    followup:bool=False

class FocusedAnswer(Contract):
    status:Literal['answered','not_found','off_topic']='answered'
    reply:ChatText
    references:list[Text]=Field(default_factory=list,max_length=4)
