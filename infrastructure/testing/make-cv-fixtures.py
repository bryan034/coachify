"""Create small, reproducible synthetic documents for the browser CV tests."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from xml.sax.saxutils import escape

target = Path(__file__).resolve().parents[2] / 'apps/frontend/tests/fixtures'
target.mkdir(parents=True, exist_ok=True)
for name, marker in [('synthetic-cv.docx', ''), ('synthetic-cv-failure.docx', 'SYNTHETIC_PROVIDER_FAILURE'),
                     ('synthetic-clarification-cv.docx', 'SYNTHETIC_CLARIFICATION_FLOW'),
                     ('synthetic-completion-cv.docx', 'SYNTHETIC_C_SERIES_COMPLETION')]:
    paragraphs = [
        'SYNTHETIC_CV_FIXTURE_V1 ' + marker,
        'Education: Synthetic University, Computer Science.',
        'Project: Team dashboard using Python and SQL.',
    ]
    if marker == 'SYNTHETIC_CLARIFICATION_FLOW':
        paragraphs.append('Experience: Synthetic internship supporting Python reporting with a team.')
    document = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    document += ''.join('<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>' for text in paragraphs)
    document += '</w:body></w:document>'
    content_types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    with ZipFile(target / name, 'w') as archive:
        for path, content in [('[Content_Types].xml', content_types), ('word/document.xml', document)]:
            entry = ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content)
