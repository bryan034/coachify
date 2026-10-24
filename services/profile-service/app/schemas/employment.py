from pydantic import BaseModel


class EmploymentOption(BaseModel):
    id: str
    name: str
