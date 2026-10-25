"""CV-owned immutable structured records. No raw CV/JD buffers are stored."""
from bson import BSON, ObjectId
from bson.codec_options import CodecOptions
from pymongo.errors import DuplicateKeyError
from app.schemas.cv import CvSnapshot, object_id


class CvRepository:
    def __init__(self, database):
        self.collection = database.get_collection("cvs", codec_options=CodecOptions(tz_aware=True))

    def ensure_indexes(self):
        self.collection.create_index([('user_id', 1), ('created_at', -1)])

    def save(self, data, owner):
        record = CvSnapshot.model_validate(data)
        if record.user_id != owner:
            raise ValueError('CV ownership mismatch.')
        payload = record.model_dump(mode='json', by_alias=True)
        payload.update(_id=ObjectId(record.id), created_at=record.created_at, updated_at=record.updated_at)
        try:
            self.collection.insert_one(payload)
        except DuplicateKeyError:
            if BSON.encode(self.collection.find_one({'_id': payload['_id']})) != BSON.encode(payload):
                raise ValueError('CV revision ID already used with different content.') from None
        return record

    def get(self, identifier, owner):
        data = self.collection.find_one({'_id': ObjectId(object_id(identifier)), 'user_id': owner})
        return CvSnapshot.model_validate(data) if data else None
