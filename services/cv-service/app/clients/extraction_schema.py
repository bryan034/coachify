"""Provider schema derived from the authoritative extraction model."""
from copy import deepcopy
from app.schemas.cv import Extraction


# Gemini's decoding grammar can reject nested array/range combinations even
# though they are valid JSON Schema. Domain models still enforce every bound.
_DECODING_BOUNDS = frozenset({'minLength', 'maxLength', 'minItems', 'maxItems',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'})


def extraction_schema(*, gemini=False):
    schema = deepcopy(Extraction.model_json_schema())
    definitions = schema.pop('$defs', {})

    def normalize(value):
        if isinstance(value, list): return [normalize(item) for item in value]
        if not isinstance(value, dict): return value
        if '$ref' in value:
            value = {**definitions[value['$ref'].removeprefix('#/$defs/')],
                     **{key: item for key, item in value.items() if key != '$ref'}}
        # Annotation names can also be property names (notably the required
        # CV item "title"). Strip annotations only on schema nodes, never on
        # the properties mapping itself.
        result = {}
        for key, item in value.items():
            if key in ('default', 'title') or (gemini and key in _DECODING_BOUNDS): continue
            result[key] = ({name: normalize(field) for name, field in item.items()}
                           if key == 'properties' else normalize(item))
        if result.get('type') == 'object':
            result['additionalProperties'] = False
            # Strict compatible APIs require every property. Unknown optional
            # scalars are nullable; absent collections use [] and ongoing false.
            result['required'] = list(result.get('properties', {}))
        return result

    return normalize(schema)
