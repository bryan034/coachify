class CvError(Exception):
    def __init__(self, detail, status=422):
        super().__init__(detail)
        self.detail, self.status = detail, status


class Conflict(CvError):
    def __init__(self, detail='This CV changed in another session. Refresh and reconcile your saved draft before retrying.'):
        super().__init__(detail, 409)


class Missing(CvError):
    def __init__(self): super().__init__('This CV or operation was not found.', 404)
