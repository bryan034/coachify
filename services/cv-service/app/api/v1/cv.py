from pathlib import PurePosixPath
from uuid import UUID
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from app.core.auth import bearer, current_account
from app.domain.errors import Conflict, CvError
from app.domain.service import detail, selection_view
from app.schemas.cv import Mutation, SelectionMutation, ItemMutation, AnswerMutation, PrepareMutation
from app.schemas.cv import CvDetail, CvList, Selection, QuestionEnvelope, CapabilityInput, Policy, ApiError, ConfirmedContext
from app.clarification.service import answer, prepare, envelope, context_identity, retry_interpretation
from app.domain import reconciliation
from app.schemas.reconciliation import ReconcileMutation, ReconciliationView, CompareSourceMutation
from app.schemas.handoff import AnalysisInput, SourceSnapshot, DeclarationLinks
from app.domain.attachments import assess_links

router = APIRouter(prefix='/api/v1/cv', responses={code: {'model': ApiError} for code in (401,403,404,409,413,415,422,503)})


async def authenticated(request: Request, credentials=Depends(bearer)):
    return await current_account(request, credentials)


def service(request): return request.app.state.service


@router.get('/policy', response_model=Policy)
async def policy(request: Request, account=Depends(authenticated)):
    return {**request.app.state.settings.policy(), 'max_item_chars': 4000,
            'extraction_configured': request.app.state.extractor.configured}


@router.get('', response_model=CvList)
async def listing(request: Request, account=Depends(authenticated)):
    repo = request.app.state.repository
    return {'cvs': [detail(doc) for doc in await run_in_threadpool(repo.list, account['id'])],
            'selection': selection_view(await run_in_threadpool(repo.selection, account['id']))}


@router.get('/declaration-links', response_model=DeclarationLinks)
async def declaration_links(request: Request, account=Depends(authenticated)):
    manual = await declarations(request, account)
    repo = request.app.state.repository
    selection = await run_in_threadpool(repo.selection, account['id'])
    links = await run_in_threadpool(assess_links, repo, account['id'], manual['declarations'], selection['selected_cv_id'])
    return {'declarations_version': manual['version'], 'links': links}


@router.post('/uploads', status_code=202, response_model=CvDetail, openapi_extra={'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {'type': 'object', 'required': ['file', 'mutation_id'], 'properties': {'file': {'type': 'string', 'format': 'binary'}, 'mutation_id': {'type': 'string', 'format': 'uuid'}, 'cv_id': {'type': 'string', 'format': 'uuid'}, 'expected_version': {'type': 'integer', 'minimum': 0}}, 'additionalProperties': False}}}}})
async def upload(request: Request, account=Depends(authenticated)):
    maximum = request.app.state.settings.max_file_bytes
    if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
        raise HTTPException(415, 'Upload one PDF or DOCX with its mutation ID as multipart form data.')
    async with request.form(max_files=1, max_fields=3, max_part_size=1024) as form:
        file = form.get('file')
        allowed = {'file', 'mutation_id', 'cv_id', 'expected_version'}
        if not isinstance(file, UploadFile) or any(key not in allowed for key in form) or len(form.multi_items()) != len(form):
            raise HTTPException(422, 'Choose one file and provide the upload mutation ID.')
        try:
            mutation_id = str(UUID(str(form.get('mutation_id', ''))))
            cv_id = str(UUID(str(form['cv_id']))) if form.get('cv_id') else None
            expected = int(str(form['expected_version'])) if form.get('expected_version') is not None else None
            if (cv_id is None) != (expected is None) or (expected is not None and expected < 0): raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(422, 'Provide a valid mutation ID and matching CV/version for reprocessing.')
        name = PurePosixPath((file.filename or '').replace('\\', '/')).name
        if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
            raise HTTPException(422, 'Choose a file with a readable name of at most 200 characters.')
        extension = PurePosixPath(name).suffix.lower()
        content_types = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
        if extension not in content_types or file.content_type not in {content_types.get(extension), 'application/octet-stream'}:
            raise HTTPException(422, 'Choose a PDF or DOCX whose actual format matches its file extension.')
        data = await file.read(maximum + 1)
        if not data: raise HTTPException(422, 'Choose a non-empty PDF or DOCX file.')
        if len(data) > maximum: raise HTTPException(413, 'This file exceeds the configured upload limit.')
        # Cheap signatures reject renamed files before queueing; bounded parser
        # performs complete format/encryption/text checks inside the isolated worker.
        if extension == '.pdf' and not data.startswith(b'%PDF-'):
            raise HTTPException(422, 'The file content does not match PDF format.')
        if extension == '.docx' and not data.startswith(b'PK\x03\x04'):
            raise HTTPException(422, 'The file content does not match DOCX format.')
        result = await run_in_threadpool(service(request).upload, account['id'], account['profile_version'], name,
                                        extension[1:], data, mutation_id, cv_id, expected)
    return detail(result)


@router.get('/operations/{operation_id}', response_model=CvDetail)
async def operation(operation_id: str, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(service(request).operation, account['id'], operation_id))


@router.post('/operations/{operation_id}/retry', response_model=CvDetail)
async def retry(operation_id: str, mutation: Mutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(service(request).retry, account['id'], operation_id, mutation))


@router.put('/selection', response_model=Selection)
async def select(mutation: SelectionMutation, request: Request, account=Depends(authenticated)):
    return selection_view(await run_in_threadpool(service(request).select, account['id'], mutation))


@router.get('/{cv_id}', response_model=CvDetail)
async def read(cv_id: str, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(service(request).get, account['id'], cv_id))


@router.patch('/{cv_id}/items/{item_id}', response_model=CvDetail)
async def edit(cv_id: str, item_id: str, mutation: ItemMutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(service(request).edit, account['id'], cv_id, item_id, mutation))


@router.get('/{cv_id}/clarifications', response_model=QuestionEnvelope)
async def clarifications(cv_id: str, request: Request, account=Depends(authenticated)):
    await run_in_threadpool(service(request).get, account['id'], cv_id)
    context = await request.app.state.target_provider.selected_context(account['authorization'])
    # Read the CV after the network request so a concurrent save is reflected in
    # this envelope's cv_version, which clients pair with their detail snapshot.
    doc = await run_in_threadpool(service(request).get, account['id'], cv_id)
    return envelope(doc, context)


@router.post('/{cv_id}/clarifications/prepare', response_model=QuestionEnvelope)
async def prepare_questions(cv_id: str, mutation: PrepareMutation, request: Request, account=Depends(authenticated)):
    await run_in_threadpool(service(request).get, account['id'], cv_id)
    context = await request.app.state.target_provider.context(account['authorization'], mutation.career_target_id, mutation.career_target_version)
    result = await run_in_threadpool(prepare, service(request), account['id'], cv_id, mutation, context)
    selected = await request.app.state.target_provider.selected_context(account['authorization'])
    before = ConfirmedContext.model_validate(context) if context is not None else None
    after = ConfirmedContext.model_validate(selected) if selected is not None else None
    if context_identity(before) != context_identity(after):
        # Preparation saves question identity only, never new capability facts.
        # A target switch keeps that history but must not report a current result.
        raise Conflict('Your selected Career target changed while preparing questions. Refresh and prepare again.')
    return result


@router.put('/{cv_id}/clarifications/{question_id}', response_model=CvDetail)
async def save_answer(cv_id: str, question_id: str, mutation: AnswerMutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(answer, service(request), account['id'], cv_id, question_id, mutation,
                                        request.app.state.interpreter))


@router.post('/{cv_id}/clarifications/{question_id}/interpretation/retry', response_model=CvDetail)
async def reinterpret_answer(cv_id: str, question_id: str, mutation: Mutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(retry_interpretation, service(request), account['id'], cv_id,
                                        question_id, mutation, request.app.state.interpreter))


@router.get('/{cv_id}/reconciliation', response_model=ReconciliationView | None)
async def read_reconciliation(cv_id: str, request: Request, account=Depends(authenticated)):
    return reconciliation.view(await run_in_threadpool(service(request).get, account['id'], cv_id))


@router.post('/{cv_id}/reconciliation', response_model=CvDetail)
async def resolve_reconciliation(cv_id: str, mutation: ReconcileMutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(reconciliation.resolve, service(request), account['id'], cv_id, mutation))


@router.post('/{cv_id}/reconciliation/compare', response_model=CvDetail)
async def compare_replacement(cv_id: str, mutation: CompareSourceMutation, request: Request, account=Depends(authenticated)):
    return detail(await run_in_threadpool(reconciliation.compare_source, service(request), account['id'], cv_id, mutation))


async def declarations(request, account):
    try:
        response = await request.app.state.profile_client.get('/api/v1/profile/capabilities',
            headers={'Authorization': account['authorization']})
        if response.status_code == 401: raise HTTPException(401, 'Your session has ended. Sign in again.')
        if response.status_code != 200: raise ValueError
        result = response.json()
        if not isinstance(result, dict) or type(result.get('version')) is not int or not isinstance(result.get('declarations'), list): raise ValueError
        return result
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, 'Manual capability inputs are unavailable. Retry before using this CV.') from exc


@router.get('/{cv_id}/capability-input', response_model=SourceSnapshot)
async def capability_input(cv_id: str, request: Request, expected_version: int = Query(ge=0),
        expected_selection_version: int = Query(ge=0), expected_declarations_version: int = Query(ge=0),
        account=Depends(authenticated)):
    repo = request.app.state.repository
    selected = await run_in_threadpool(repo.selection, account['id'])
    current = await run_in_threadpool(service(request).get, account['id'], cv_id)
    if selected['selected_cv_id'] != cv_id or selected['version'] != expected_selection_version:
        raise Conflict('CV selection changed. Review the selected source before continuing.')
    if current['version'] != expected_version or current['operation']['status'] != 'ready' or current.get('candidate'):
        raise Conflict('The selected CV changed or is not ready. Refresh its saved result.')
    manual = await declarations(request, account)
    if manual['version'] != expected_declarations_version: raise Conflict('Manual capabilities changed. Refresh before continuing.')
    # Re-read each authority; this establishes a captured version vector, not a
    # cross-service transaction. Consumers store this exact snapshot and revalidate
    # against target/source revisions at analysis admission.
    again = await declarations(request, account)
    latest = await run_in_threadpool(service(request).get, account['id'], cv_id)
    current_selection = await run_in_threadpool(repo.selection, account['id'])
    if latest['version'] != expected_version or current_selection['version'] != expected_selection_version or again['version'] != manual['version']:
        raise Conflict('Capability inputs changed while being assembled. Refresh and retry.')
    result = detail(current)
    links = await run_in_threadpool(assess_links, repo, account['id'], manual['declarations'], cv_id)
    return {'cv_id': cv_id, 'cv_version': current['version'], 'upload_profile_version': current['profile_version'],
        'declaration_links': links, 'selection_version': selected['version'], 'extraction_version': result['extraction_version'],
        'effective_version': result['effective_version'], 'declarations_version': manual['version'],
        'profile_version': current['profile_version'], 'items': [item for item in result['items'] if not item['removed']],
        'skills': result['skills'], 'declarations': manual['declarations'], 'schema_version': '1', 'normalization_version': '1'}


@router.get('/{cv_id}/analysis-input', response_model=AnalysisInput)
async def analysis_input(cv_id: str, request: Request, expected_version: int = Query(ge=0),
        expected_selection_version: int = Query(ge=0), expected_declarations_version: int = Query(ge=0),
        expected_target_id: str = Query(min_length=1, max_length=100), expected_target_version: int = Query(ge=1),
        expected_target_selection_version: int = Query(ge=1), account=Depends(authenticated)):
    """Target-bound producer snapshot. This endpoint does not start an analysis."""
    await run_in_threadpool(service(request).get, account['id'], cv_id)
    raw = await request.app.state.target_provider.selected_context(account['authorization'])
    target = ConfirmedContext.model_validate(raw) if raw is not None else None
    if target is None or (target.id, target.version, target.selection_version) != (
            expected_target_id, expected_target_version, expected_target_selection_version):
        raise Conflict('Confirm and select the expected Career target before assembling these inputs.')
    snapshot = await capability_input(cv_id, request, expected_version, expected_selection_version,
                                      expected_declarations_version, account)
    document = await run_in_threadpool(service(request).get, account['id'], cv_id)
    if any(q.get('interpretation_status') in {'pending', 'failed'} and not q.get('reconciliation_required')
           for q in document['clarifications']):
        raise Conflict('A saved explanation still needs interpretation. Retry it before using these inputs.')
    current_raw = await request.app.state.target_provider.selected_context(account['authorization'])
    current_target = ConfirmedContext.model_validate(current_raw) if current_raw is not None else None
    latest = await run_in_threadpool(service(request).get, account['id'], cv_id)
    selection = await run_in_threadpool(request.app.state.repository.selection, account['id'])
    manual = await declarations(request, account)
    if (context_identity(current_target) != context_identity(target) or latest['version'] != expected_version
            or selection['version'] != expected_selection_version or manual['version'] != expected_declarations_version):
        raise Conflict('The target or capability inputs changed during assembly. Refresh and retry.')
    return {'schema_version': '2', 'capabilities': snapshot, 'target': target.model_dump(mode='json'),
            'requires_consumer_revalidation': True}
