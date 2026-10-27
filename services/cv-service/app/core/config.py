"""One server-owned policy is also returned to the upload UI."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_file_bytes: int = 10 * 1024 * 1024
    max_text_chars: int = 100_000
    max_items: int = 160
    max_evidence_chars: int = 500
    original_retention_hours: int = 24
    lease_seconds: int = 180
    max_attempts: int = 3
    storage_path: str = '/tmp/coachify-cv'

    @classmethod
    def environment(cls):
        maximum = int(os.getenv('CV_MAX_FILE_BYTES', str(10 * 1024 * 1024)))
        if not 1024 <= maximum <= 20 * 1024 * 1024:
            raise RuntimeError('CV_MAX_FILE_BYTES must be between 1024 and 20971520.')
        return cls(max_file_bytes=maximum, storage_path=os.getenv('CV_STORAGE_PATH', '/tmp/coachify-cv'))

    def policy(self):
        return {'formats': ['pdf', 'docx'], 'max_file_bytes': self.max_file_bytes,
                'max_text_chars': self.max_text_chars, 'max_answer_chars': 4000,
                'max_title_chars': 200, 'max_description_chars': 4000,
                'original_retention_hours': self.original_retention_hours,
                'ocr_supported': False}
