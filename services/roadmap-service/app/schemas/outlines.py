"""Request contracts for user-editable roadmap outlines."""
from .base import Mutation
from .roadmap import OutlineDraft, RoutineRule

class EditOutline(Mutation):
    outline:OutlineDraft
