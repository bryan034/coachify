"""Project server schemas into a bounded-complexity Gemini decoding grammar.

The original Pydantic models remain authoritative for validation and persistence.
Nested reference/length/range combinations can be valid JSON Schema yet fail
Gemini's decoder compilation with a bare INVALID_ARGUMENT response.
"""

_BOUNDS = frozenset({
    'minLength', 'maxLength', 'minItems', 'maxItems', 'minimum', 'maximum',
    'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
})


def gemini_schema(schema):
    definitions = schema.get('$defs', {})

    def project(value, references=()):
        if isinstance(value, list):
            return [project(item, references) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            reference = value['$ref']
            prefix = '#/$defs/'
            if not isinstance(reference, str) or not reference.startswith(prefix):
                raise ValueError('Only local model definitions are supported.')
            name = reference[len(prefix):].replace('~1', '/').replace('~0', '~')
            if name not in definitions or name in references:
                raise ValueError('Model definitions must be finite and resolvable.')
            expanded = {**definitions[name], **{k: v for k, v in value.items() if k != '$ref'}}
            return project(expanded, (*references, name))
        result = {}
        for key, item in value.items():
            if key == '$defs' or key in _BOUNDS:
                continue
            # Property names are data, including names that match schema keywords.
            result[key] = ({name: project(child, references) for name, child in item.items()}
                           if key == 'properties' else project(item, references))
        if result.get('type') == 'object' and 'properties' in result:
            # Fixed object shapes reduce optional-field branching. Existing null
            # unions and enums survive; arrays can be empty where data is unknown.
            result['required'] = list(result['properties'])
        return result

    return project(schema)
