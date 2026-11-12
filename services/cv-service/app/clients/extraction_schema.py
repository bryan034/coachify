"""Provider schema derived from the authoritative extraction model."""
from copy import deepcopy
from app.schemas.cv import Extraction


def extraction_schema():
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
            if key in ('default', 'title'): continue
            result[key] = ({name: normalize(field) for name, field in item.items()}
                           if key == 'properties' else normalize(item))
        if result.get('type') == 'object':
            result['additionalProperties'] = False
            # Strict compatible APIs require every property. Unknown optional
            # scalars are nullable; absent collections use [] and ongoing false.
            result['required'] = list(result.get('properties', {}))
        return result

    return normalize(schema)
