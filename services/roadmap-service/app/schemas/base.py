from typing import Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]
class Contract(BaseModel): model_config=ConfigDict(extra='forbid')
class Mutation(Contract):
    expected_version:int=Field(strict=True,ge=0)
    mutation_id:UUID
