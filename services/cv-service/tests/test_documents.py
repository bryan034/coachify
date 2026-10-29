from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.parsing.documents import parse_document
from app.domain.capabilities import validate_extraction, skill_id
from tests.conftest import docx


def pdf(text='Education at Example University', encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(500, 500)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    if text:
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 10 450 Td (' + text + ') Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted: writer.encrypt('secret')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_docx_sources_and_size_boundary():
    for data, extension, location in ((docx(), '.docx', 'Paragraph 1'), (pdf(), '.pdf', 'Page 1')):
        result = parse_document(data, extension, max_file_bytes=len(data))
        assert result['blocks'][0]['location'] == location
        with pytest.raises(ValueError, match='limit'): parse_document(data, extension, max_file_bytes=len(data)-1)


@pytest.mark.parametrize('data,extension,phrase', [(b'', '.pdf', 'non-empty'), (b'plain text', '.pdf', 'format'),
    (b'%PDF-broken', '.pdf', 'read'), (pdf(encrypted=True), '.pdf', 'Password'), (pdf(text=''), '.pdf', 'No readable'),
    (b'not a zip', '.docx', 'read'), (docx(), '.txt', 'Choose a PDF')])
def test_rejected_documents(data, extension, phrase):
    with pytest.raises(ValueError, match=phrase): parse_document(data, extension)


def test_docx_expansion_and_entities_are_bounded():
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', 'x' * (33 * 1024 * 1024))
    with pytest.raises(ValueError, match='expands'): parse_document(output.getvalue(), '.docx')
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>')
    with pytest.raises(ValueError, match='safely'): parse_document(output.getvalue(), '.docx')


def test_strict_model_output_and_source_identity():
    blocks = [{'id': 'b1', 'location': 'Paragraph 1', 'text': 'Python software project'}]
    base = {'kind': 'skill', 'title': 'Python', 'description': 'Python software project', 'explicit': True,
            'evidence': [{'block_id': 'b1', 'excerpt': 'Python software project'}]}
    first = validate_extraction({'items': [base]}, blocks, 'cv-a')
    assert first[0]['proficiency'] is None and first[0]['experience_months'] is None
    assert first[0]['id'] != validate_extraction({'items': [base]}, blocks, 'cv-b')[0]['id']
    for change in ({'explicit': 'false'}, {'experience_months': '12'}, {'experience_months': -1}, {'experience_months': float('inf')},
                   {'evidence': [{'block_id': 'b2', 'excerpt': 'Python'}]}, {'supporting_items': [0]}, {'extra': 'untrusted'}):
        with pytest.raises(ValueError): validate_extraction({'items': [{**base, **change}]}, blocks, 'cv-a')
    with pytest.raises(ValueError): validate_extraction({'items': []}, blocks, 'cv-a')
    assert skill_id('  Machine  LEARNING ') == 'skill:machine learning'
    assert skill_id('C++') != skill_id('C#')


def test_dense_acyclic_dependencies_are_linear_and_cycles_rejected():
    from time import monotonic
    blocks = [{'id': f'b{i}', 'location': f'Paragraph {i}', 'text': f'Education claim {i}'} for i in range(80)]
    items = [{'kind': 'education', 'title': f'Claim {i}', 'description': block['text'], 'explicit': True,
        'evidence': [{'block_id': block['id'], 'excerpt': block['text']}],
        'supporting_items': list(range(max(0, i-15), i))} for i, block in enumerate(blocks)]
    started = monotonic()
    assert len(validate_extraction({'items': items}, blocks, 'dense-cv')) == 80
    assert monotonic() - started < 2
    items[0]['supporting_items'] = [79]
    with pytest.raises(ValueError, match='circular'): validate_extraction({'items': items}, blocks, 'dense-cv')


def test_normalized_repeated_skill_labels_keep_one_support_source():
    blocks = [{'id': 'b1', 'location': 'Page 1', 'text': 'Python project'}]
    items = validate_extraction({'items': [{'kind': 'skill', 'title': 'Python', 'description': 'Python project',
        'explicit': True, 'evidence': [{'block_id': 'b1', 'excerpt': 'Python project'}],
        'skill_names': ['Python', 'python', ' PYTHON ']}]}, blocks, 'source')
    assert items[0]['skill_ids'] == ['skill:python']


def test_concurrent_private_original_publication_is_complete(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    from app.repositories.files import FileStore
    files = FileStore(str(tmp_path))
    identifier, data = str(uuid4()), b'synthetic bytes' * 1000
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: files.write(identifier, data), range(8)))
    assert files.read(identifier) == data
    assert {path.name for path in tmp_path.iterdir()} == {identifier, '.locks'}
    assert files.lock_root.is_dir() and len(list(files.lock_root.iterdir())) <= 256
    assert files.lock_root.stat().st_mode & 0o777 == 0o700
    assert files.path(identifier).stat().st_mode & 0o777 == 0o600
