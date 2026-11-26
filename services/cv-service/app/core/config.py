"""One server-owned policy is also returned to the upload UI."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_file_bytes: int = 10 * 1024 * 1024
    max_text_chars: int = 100_000
    original_retention_hours: int = 24
    lease_seconds: int = 180
    max_attempts: int = 3
    extraction_auto_retries: int = 2
    extraction_retry_delays: tuple[int, ...] = (20, 40)
    storage_path: str = '/tmp/elo-cv'
    max_saved_cvs_per_owner: int = 3
    max_original_bytes_per_owner: int = 100 * 1024 * 1024
    model_calls_per_owner_per_day: int = 120
    model_concurrent_per_owner: int = 1
    interview_max_target_attempts: int = 1

    @classmethod
    def environment(cls):
        maximum = int(os.getenv('CV_MAX_FILE_BYTES', str(10 * 1024 * 1024)))
        if not 1024 <= maximum <= 20 * 1024 * 1024:
            raise RuntimeError('CV_MAX_FILE_BYTES must be between 1024 and 20971520.')
        limits = {}
        for name, default, upper in (
            ('max_saved_cvs_per_owner', 3, 20_000),
            ('max_original_bytes_per_owner', 100 * 1024 * 1024, 1024 ** 4),
            ('model_calls_per_owner_per_day', 120, 1_000_000),
            ('interview_max_target_attempts', 1, 5), ('model_concurrent_per_owner', 1, 31)):
            value = int(os.getenv('CV_' + name.upper(), str(default)))
            if not 1 <= value <= upper: raise RuntimeError('CV_' + name.upper() + f' must be between 1 and {upper}.')
            limits[name] = value
        return cls(max_file_bytes=maximum, storage_path=os.getenv('CV_STORAGE_PATH', '/tmp/elo-cv'), **limits)

    def policy(self):
        return {'formats': ['pdf', 'docx'], 'max_file_bytes': self.max_file_bytes,
                'max_text_chars': self.max_text_chars, 'max_answer_chars': 4000,
                'max_title_chars': 200, 'max_description_chars': 4000,
                'original_retention_hours': self.original_retention_hours,
                'ocr_supported': False, 'max_saved_cvs': self.max_saved_cvs_per_owner,
                'max_stored_original_bytes': self.max_original_bytes_per_owner,
                'max_model_calls_per_day': self.model_calls_per_owner_per_day,
                'max_concurrent_model_calls': self.model_concurrent_per_owner}
