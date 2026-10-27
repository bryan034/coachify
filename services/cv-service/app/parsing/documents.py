"""Bounded source blocks; parsed document text never enters persistent records."""
from io import BytesIO
from zipfile import ZipFile
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader


def parse_document(data, extension, max_file_bytes=10 * 1024 * 1024, max_text_chars=100_000):
    if not data:
        raise ValueError('Choose a non-empty PDF or DOCX file.')
    if len(data) > max_file_bytes:
        raise ValueError('This file exceeds the configured upload limit. Choose a smaller file.')
    blocks, notices = [], []
    count = 0

    def add(text, location):
        nonlocal count
        text = text.strip()
        count += len(text)
        if count > max_text_chars:
            raise ValueError('This CV exceeds the 100,000 character processing limit; nothing was truncated.')
        if text:
            blocks.append({'id': f'b{len(blocks) + 1}', 'location': location, 'text': text})

    if extension == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('The file content does not match PDF format. Choose the original PDF or a DOCX.')
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError('Password-protected PDFs are not supported. Upload an unencrypted copy.')
            if len(reader.pages) > 100:
                raise ValueError('Choose a CV with at most 100 pages.')
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                add(text, f'Page {number}')
                if not text.strip():
                    notices.append(f'Page {number} has no readable text; OCR is not available.')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('This PDF could not be read. Export a new text-based PDF or DOCX and retry.') from exc
    elif extension == '.docx':
        try:
            with ZipFile(BytesIO(data)) as archive:
                info, names = archive.infolist(), set(archive.namelist())
                if len(info) > 1000 or sum(item.file_size for item in info) > 32 * 1024 * 1024:
                    raise ValueError('This DOCX expands beyond the processing limit. Export a simpler CV.')
                if len(names) != len(info):
                    raise ValueError('This DOCX contains duplicate archive entries. Export a new copy.')
                if any(item.flag_bits & 1 for item in info) or any('vbaproject' in name.lower() for name in names):
                    raise ValueError('Encrypted or macro-containing documents are not supported.')
                if not {'[Content_Types].xml', 'word/document.xml'} <= names:
                    raise ValueError('The file content does not match DOCX format.')
                root = ElementTree.fromstring(archive.read('word/document.xml'))
                namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                for number, paragraph in enumerate(root.iter(namespace + 'p'), 1):
                    parts = []
                    for item in paragraph.iter():
                        if item.tag == namespace + 't': parts.append(item.text or '')
                        elif item.tag == namespace + 'tab': parts.append('\t')
                        elif item.tag in {namespace + 'br', namespace + 'cr'}: parts.append('\n')
                    add(''.join(parts), f'Paragraph {number}')
        except DefusedXmlException as exc:
            raise ValueError('This DOCX could not be read safely. Export a new copy.') from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('This DOCX could not be read safely. Export a new DOCX or text-based PDF.') from exc
    else:
        raise ValueError('Choose a PDF or DOCX file.')
    if not blocks:
        raise ValueError('No readable text was found. Scanned/image-only CVs need a text-based export; OCR is not available.')
    return {'blocks': blocks, 'notices': notices}
