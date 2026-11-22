import asyncio
import json
import logging

from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool as thread

from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.errors import AIError
from app.ai.routing import chat_models
from app.repositories.goals import fingerprint, now
from app.repositories.round_titles import RoundTitleStore, TITLE_TIMEOUT_SECONDS
from app.schemas.opportunity import CategoryResult
from app.schemas.round_titles import RoundTitles, TITLE_WORDS
from app.workflows.boundaries import UnexpectedFailure, contained

log = logging.getLogger('uvicorn.error.round_titles')
POLL_SECONDS = 0.2


def round_names(categories):
    category = categories.get('interview_intelligence')
    if not category:
        return {}
    result = category if isinstance(category, CategoryResult) else CategoryResult.model_validate(category)
    names = {}
    for finding in result.findings:
        if finding.round_number is not None:
            values = names.setdefault(str(finding.round_number), [])
            if finding.round_name and finding.round_name not in values:
                values.append(finding.round_name)
    return names


def validate_titles(output, expected):
    numbers = [str(item.round_number) for item in output.titles]
    if len(numbers) != len(set(numbers)) or set(numbers) != set(expected):
        raise AIError('invalid_output', reason='provenance', fields=('titles', 'round_number'))


async def generate_titles(request, account, store, key, names, fallback):
    titles = dict(fallback)
    try:
        payload = {'rounds': [{'round_number': int(number), 'names': values} for number, values in names.items()]}
        async with asyncio.timeout(TITLE_TIMEOUT_SECONDS):
            result = await contained(chat_models(request.app.state).generate(
                AIInput(stage='interview_round_titles', context=json.dumps(payload)),
                Operation(account, key, 'interview_round_titles'), current_revision=lambda: key,
                validate_output=lambda output: validate_titles(output, names)),
                (AIError, ValueError, PyMongoError, TimeoutError))
        output = RoundTitles.model_validate(result.data.model_dump())
        validate_titles(output, names)
        titles = {str(item.round_number): item.title for item in output.titles}
    except (AIError, ValueError, PyMongoError, TimeoutError, UnexpectedFailure) as error:
        log.warning('round_title_shortening_failed error_code=%s', getattr(error, 'code', type(error).__name__))
    finally:
        try:
            await asyncio.shield(thread(store.finish, key, titles))
        except PyMongoError:
            log.warning('round_title_cache_unavailable')
    return titles


async def prepare(request, account, categories, finished=True):
    names = round_names(categories)
    titles = {}
    long = {}
    for number, values in names.items():
        name = ' / '.join(values) or f'Round {number}'
        if len(name.split()) <= TITLE_WORDS:
            titles[number] = name
        else:
            titles[number] = f'Round {number}'
            long[number] = values
    if not long or not finished:
        return titles
    store = RoundTitleStore(request.app.state.opportunities.store.rows)
    key = 'round-titles:' + fingerprint({'format': 1, 'names': long})
    fallback = {number: titles[number] for number in long}
    try:
        if await thread(store.reserve, key):
            titles.update(await asyncio.shield(generate_titles(request, account, store, key, long, fallback)))
        else:
            while (saved := await thread(store.read, key)) and saved['state'] == 'running' and saved['deadline'] > now():
                await asyncio.sleep(POLL_SECONDS)
            if saved and saved['state'] == 'done':
                output = RoundTitles(titles=[{'round_number': int(number), 'title': title} for number, title in saved['titles'].items()])
                validate_titles(output, long)
                titles.update({str(item.round_number): item.title for item in output.titles})
    except (AIError, AttributeError, KeyError, PyMongoError, TypeError, ValueError):
        log.warning('round_title_cache_unavailable')
    return titles
