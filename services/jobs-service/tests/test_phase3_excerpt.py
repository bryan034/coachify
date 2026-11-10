from app.normalise import excerpt

def test_role_excerpt_prefers_requirements_over_employer_boilerplate():
    text='Synthetic Company makes rockets. Requirements:\nPython and SQL for the internship.'
    value=excerpt(text)
    assert 'Python and SQL' in value
    assert 'makes rockets' not in value
