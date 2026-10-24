"""Pure document readers. Executed in a resource-bounded child process."""
from io import BytesIO
from zipfile import ZipFile
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader
from app.schemas.preview import MAX_FILE, MAX_TEXT


def validate_text(text):
    if not text.strip():
        raise ValueError('No readable text was found. Paste the description or choose another file; scanned PDFs require OCR, which is not available yet.')
    if len(text) > MAX_TEXT:
        raise ValueError('The preview exceeds 20,000 characters. Paste just one job description instead; nothing was truncated.')
    return text


def document_text(data, extension):
    if not data or len(data) > MAX_FILE:
        raise ValueError('Choose a non-empty file up to 10 MiB.')
    notices = ['Check the extracted text, especially bullet lists, tables and page order. This preview is temporary.']
    if extension == '.txt':
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('TXT files must use UTF-8 encoding. Save as UTF-8 or paste the description.') from exc
        if any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise ValueError('This is not a readable TXT document. Choose PDF, DOCX or UTF-8 TXT.')
    elif extension == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('The file content does not match PDF format.')
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError('Password-protected PDFs are not supported. Upload an unencrypted copy or paste the text.')
            if len(reader.pages) > 100:
                raise ValueError('Choose a document with at most 100 pages.')
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or '')
                if sum(map(len, pages)) > MAX_TEXT:
                    raise ValueError('The preview exceeds 20,000 characters. Paste just one job description instead.')
            text = '\n\n'.join(pages)
            if any(not page.strip() for page in pages):
                notices.append('Some PDF pages have no readable text and may be scanned. Check for missing content; OCR is not available.')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('This PDF could not be read. Try another file or paste the description.') from exc
    elif extension == '.docx':
        try:
            with ZipFile(BytesIO(data)) as archive:
                info = archive.infolist()
                names = set(archive.namelist())
                if len(info) > 1000 or sum(i.file_size for i in info) > 32 * 1024 * 1024:
                    raise ValueError('This DOCX expands beyond the processing limit. Paste the description instead.')
                if any(i.flag_bits & 1 for i in info) or any('vbaproject' in n.lower() for n in names):
                    raise ValueError('Encrypted or macro-containing documents are not supported.')
                if not {'[Content_Types].xml', 'word/document.xml'} <= names:
                    raise ValueError('The file content does not match DOCX format.')
                root = ElementTree.fromstring(archive.read('word/document.xml'))
                w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                paragraphs = []
                for paragraph in root.iter(w + 'p'):
                    parts = []
                    for item in paragraph.iter():
                        if item.tag == w + 't': parts.append(item.text or '')
                        elif item.tag == w + 'tab': parts.append('\t')
                        elif item.tag in {w + 'br', w + 'cr'}: parts.append('\n')
                    prefix = '• ' if paragraph.find('.//' + w + 'numPr') is not None else ''
                    paragraphs.append(prefix + ''.join(parts))
                text = '\n'.join(paragraphs)
        except DefusedXmlException as exc:
            raise ValueError('This DOCX could not be read safely. Paste the description instead.') from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('This DOCX could not be read. Try another file or paste the description.') from exc
    else:
        raise ValueError('Choose a PDF, DOCX or UTF-8 TXT file.')
    return {'text': validate_text(text), 'notices': notices}
