"""Review-time skill levels: rated by the model per skill, including skipped topics, from conclusive evidence."""
import pytest
from app.domain.service import detail
from app.domain.skill_levels import apply_skill_level_reviews, coverage, pending_sources, ratable, review_source, validate_level_review
from tests.test_cv_interview import send, start_two_topics

METADATA = {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': 'cv-skill-levels-1', 'schema_version': '1'}


def item(**changes):
    return {'id': 'item-1', 'kind': 'project', 'title': 'Pipeline', 'description': 'Built and ran a Python pipeline alone.',
        'removed': False, 'evidence': [{'id': 'b1', 'location': 'Page 1', 'excerpt': 'Built and ran a Python pipeline alone.'}],
        'review_evidence': [], 'skill_claims': [
            {'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'independent'},
            {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'team', 'assistance': 'unknown'}], **changes}


def document(**changes):
    return {'clarifications': [{'id': 'q1', 'item_id': 'item-1', 'status': 'answered', 'question': 'What did you do?',
        'answer': 'I designed it and fixed production failures for two years.'}], **changes}


def rating(**changes):
    return {'item_id': 'item-1', 'skill_name': 'Python', 'level': 7, 'rationale': 'Owned a production pipeline.',
            'evidence': [{'source_id': 'answer:q1', 'quote': 'fixed production failures for two years'}], **changes}


def test_source_gives_the_model_cv_and_review_answers_but_not_team_only_skills():
    source = review_source(document(), item(), 'deferred')
    assert [s['name'] for s in source['model']['skills']] == ['Python']
    assert source['model']['review_answers'][0]['id'] == 'answer:q1' and source['model']['review_status'] == 'deferred'
    # The review status is context, not evidence: it must not make a saved review stale.
    assert source['fingerprint'] == review_source(document(), item())['fingerprint']


def test_supported_rating_is_kept_from_an_answer_or_the_cv():
    sources = [review_source(document(), item())]
    stored = validate_level_review({'levels': [rating()]}, sources)['item-1']
    assert stored['levels'][0]['level'] == 7 and stored['levels'][0]['evidence'][0]['location'] == 'Your review answer'
    cv_only = rating(evidence=[{'source_id': 'b1', 'quote': 'ran a Python pipeline alone'}])
    assert validate_level_review({'levels': [cv_only]}, sources)['item-1']['levels'][0]['evidence'][0]['location'] == 'Your CV'


@pytest.mark.parametrize('bad', [
    rating(skill_name='Rust'),                                                  # not on this source
    rating(item_id='other'),                                                    # another source
    rating(evidence=[]),                                                        # unexplained
    rating(evidence=[{'source_id': 'answer:q1', 'quote': 'I am a world expert'}]),  # invented quotation
    rating(evidence=[{'source_id': 'zz', 'quote': 'fixed production failures'}]),   # unknown source
])
def test_missing_or_unsupported_rating_assumes_the_worst(bad):
    source = review_source(document(), item())
    stored = validate_level_review({'levels': [bad]}, [source])['item-1']
    # Still rated, at the pessimistic level for unconfirmed project use; the team-only skill is never rated.
    assert [(l['skill_id'], l['level'], l.get('assumed')) for l in stored['levels']] == [('skill:python', 2, True)]
    assert stored['levels'][0]['evidence'][0]['id'] == 'b1'
    assert pending_sources(document(skill_level_reviews={'item-1': stored}), [item()]) == []


def test_conflicting_evidence_is_labelled_uncertain_not_rated():
    source = review_source(document(), item())
    saved = document(skill_level_reviews=validate_level_review(
        {'levels': [rating(level=None, rationale='The CV and the answer disagree.', evidence=[])]}, [source]))
    claim = apply_skill_level_reviews(saved, [item()])[0]['skill_claims'][0]
    assert claim['skill_level']['level'] is None and claim['skill_level']['status'] == 'uncertain'
    assert coverage([item(skill_claims=[claim])])['share'] == 0


def test_model_level_cannot_exceed_the_evidence_ceiling():
    guided = item(skill_claims=[{'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'unknown'}])
    source = review_source(document(), guided)
    assert validate_level_review({'levels': [rating(level=9)]}, [source])['item-1']['levels'][0]['level'] == 3


def test_a_bare_skill_mention_is_rated_at_the_bottom():
    bare = item(kind='skill', title='Go', description='Listed skill.', skill_claims=[
        {'skill_id': 'skill:go', 'name': 'Go', 'attribution': 'unknown', 'assistance': 'unknown'}])
    assert ratable(bare)
    stored = validate_level_review({'levels': []}, [review_source(document(clarifications=[]), bare)])['item-1']
    assert stored['levels'][0]['level'] == 1


def test_review_applies_only_while_its_evidence_is_unchanged():
    source = review_source(document(), item())
    saved = document(skill_level_reviews=validate_level_review({'levels': [rating()]}, [source]))
    claims = apply_skill_level_reviews(saved, [item()])[0]['skill_claims']
    assert claims[0]['skill_level']['level'] == 7 and claims[0]['skill_level']['source'] == 'review'
    assert 'skill_level' not in claims[1]
    changed = item(description='Helped a little with a Python pipeline.')
    assert 'skill_level' not in apply_skill_level_reviews(saved, [changed])[0]['skill_claims'][0]
    assert len(pending_sources(saved, [changed])) == 1


class Rater:
    def __init__(self, level=6, fail=False):
        self.calls, self.level, self.fail = [], level, fail

    def __call__(self, context):
        self.calls.append(context)
        if self.fail: raise ValueError('provider down')
        return {'levels': [{'item_id': source['id'], 'skill_name': skill['name'], 'level': self.level,
            'rationale': 'Described personal use in the CV.',
            'evidence': [{'source_id': 'description', 'quote': source['description']}]}
            for source in context['sources'] for skill in source['skills']]}, METADATA


def test_skipped_topics_are_rated_from_the_cv(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    provider.rate_skill_levels = rater = Rater()
    first = chat['active_question']['item_id']
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    stored = app.state.conversations.cv.get('owner-a', cv['id'])
    # Only the closed (skipped) topic is rated so far, with its skipped status as context.
    assert list(stored['skill_level_reviews']) == [first]
    assert rater.calls[0]['sources'][0]['review_status'] == 'deferred'
    view = detail(stored)
    claims = next(i for i in view['items'] if i['id'] == first)['skill_claims']
    # The skipped topic never established independent work, so the model's 6 is capped at guided use.
    assert {c['skill_level']['level'] for c in claims} == {3}
    assert all(c['skill_level']['source'] == 'review' for c in claims)
    assert next(s for s in view['skills'] if s['name'] == 'Python')['skill_level']['level'] == 3
    # Levels are an overlay: the evidence version and fingerprints are untouched.
    assert stored['effective_version'] == cv['effective_version']
    chat = send(client, chat, 'Skip all remaining topics.', command='skip_remaining', item_id=None)
    stored = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len(stored['skill_level_reviews']) == 2 and chat['interview']['status'] == 'reviewed_with_gaps'
    assert stored['profile_reviewed_effective_version'] == stored['effective_version']
    assert len(rater.calls) == 2  # The first topic is not rated twice.
    # Every skill has a level once the review is finished, even though both topics were skipped.
    assert coverage(detail(stored)['items'])['share'] >= 0.9


def test_rating_failure_never_loses_the_turn(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    provider.rate_skill_levels = Rater(fail=True)
    chat = send(client, chat, 'Skip all remaining topics.', command='skip_remaining', item_id=None)
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    stored = app.state.conversations.cv.get('owner-a', cv['id'])
    assert 'skill_level_reviews' not in stored  # Missing persisted reviews remain eligible for a model retry.
    assert coverage(detail(stored)['items'])['share'] >= 0.9
    assert pending_sources(stored, detail(stored)['items'])


def test_missing_model_rating_keeps_unverified_cv_evidence_uncertain():
    unverified = item(validation_issue={'status': 'unverified'})
    source = review_source(document(clarifications=[]), unverified)
    stored = validate_level_review({'levels': []}, [source])['item-1']
    assert stored['levels'][0]['level'] is None
    assert stored['levels'][0]['evidence'] == []


def test_completed_review_projects_fallback_without_overwriting_a_supported_level():
    source_item = item()
    stored = document(effective_version=2, profile_reviewed_effective_version=2)
    projected = apply_skill_level_reviews(stored, [source_item])
    level = projected[0]['skill_claims'][0]['skill_level']
    assert level['level'] == 2 and 'assumed' in level['rationale']
    assert 'skill_level_reviews' not in stored
    assert pending_sources(stored, projected)  # Read-time assumptions are never considered a model result.
    supported = item()
    supported['skill_claims'][0]['skill_level'] = {'level': 5, 'rationale': 'Independent work.', 'source': 'cv', 'evidence': []}
    assert apply_skill_level_reviews(stored, [supported])[0]['skill_claims'][0]['skill_level']['level'] == 5


def test_incomplete_review_does_not_project_missing_ratings():
    assert 'skill_level' not in apply_skill_level_reviews(
        document(effective_version=2, profile_reviewed_effective_version=None), [item()])[0]['skill_claims'][0]
