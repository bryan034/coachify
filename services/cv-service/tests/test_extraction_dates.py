"""Extracted dates must retain precision supported by the original evidence."""
import pytest
from app.domain.capabilities import validate_extraction


def extract(excerpts, **dates):
    blocks = [{'id': f'b{index}', 'location': 'Page 1', 'text': text}
              for index, text in enumerate(excerpts)]
    item = {'kind': 'education', 'title': 'Diploma', 'description': 'Study record',
            'explicit': True, 'evidence': [{'block_id': block['id'], 'excerpt': block['text']}
                                           for block in blocks], **dates}
    return validate_extraction({'items': [item]}, blocks, 'synthetic-date-cv')[0]


@pytest.mark.parametrize('excerpt,dates', [
    ('Graduated 2024', {'end_date': '2024'}),
    ('June 2024', {'end_date': '2024-06'}),
    ('Graduated 15 June 2024', {'end_date': '2024-06-15'}),
    ('2023-09 to present', {'start_date': '2023-09', 'ongoing': True}),
])
def test_extracted_dates_preserve_explicit_source_precision(excerpt, dates):
    result = extract([excerpt], **dates)
    for key, value in dates.items():
        assert result[key] == value
    assert result['experience_months'] is None


@pytest.mark.parametrize('excerpts,dates', [
    (['Graduated 2024'], {'end_date': '2024-06-15'}),
    (['Graduated June 2024'], {'end_date': '2024-06-15'}),
    (['June 2023 to 15 July 2024'], {'start_date': '2023-06-15'}),
    (['June', '2024'], {'end_date': '2024-06'}),
    (['Studied in 2024'], {'ongoing': True}),
    (['Graduated 2024'], {'end_date': '2025'}),
])
def test_extracted_dates_reject_unsupported_precision_and_status(excerpts, dates):
    with pytest.raises(ValueError, match='date'):
        extract(excerpts, **dates)
