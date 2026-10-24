class ProfileValidationError(Exception):
    def __init__(self, field: str, message: str):
        self.field, self.message = field, message


class PeriodNotFound(Exception):
    pass
