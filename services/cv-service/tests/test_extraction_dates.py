"""Optional extracted dates never block facts or invent unsupported precision."""
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
def test_extracted_dates_discard_unsupported_precision_and_status(excerpts, dates):
    result = extract(excerpts, **dates)
    for key in dates:
        assert result[key] == (False if key == 'ongoing' else None)
    assert result['evidence']


@pytest.mark.parametrize('value', ['June 2024', '06/2024', 'Spring 2024', '2024-02-30', '', '2024-13'])
def test_unrecognised_or_invalid_date_does_not_block_facts(value):
    result = extract(['Diploma, ' + value], end_date=value)
    assert result['end_date'] is None
    assert result['title'] == 'Diploma'
    assert result['evidence'][0]['excerpt'] == 'Diploma, ' + value


def test_conflicting_dates_do_not_block_facts():
    result = extract(['2025 to 2024'], start_date='2025', end_date='2024')
    assert result['start_date'] is None and result['end_date'] is None


def test_ongoing_date_keeps_no_end_date():
    result = extract(['2023 to present'], start_date='2023', end_date='2024', ongoing=True)
    assert result['start_date'] == '2023' and result['ongoing']
    assert result['end_date'] is None
