"""Display groups are decided by the skill's name, with its category only as a fallback."""
import pytest
from elo_shared.skill_groups import OTHER_SKILLS, skill_group, skill_groups
from elo_shared.skills import REGISTRY


@pytest.mark.parametrize('name, expected', [
    ('Python', 'Technical coding'), ('C', 'Technical coding'), ('C++', 'Technical coding'), ('REST API design', 'Technical coding'),
    ('SQL', 'Data & analytics'), ('Data cleaning', 'Data & analytics'), ('Power BI', 'Data & analytics'),
    ('Docker', 'Cloud & DevOps'), ('CI/CD', 'Cloud & DevOps'),
    ('Agile', 'Software & project management'), ('Project planning', 'Software & project management'),
    ('Figma', 'Design'),
    ('Stakeholder communication', 'Communication & leadership'), ('Technical writing', 'Communication & leadership'),
    ('Financial modelling', 'Business & finance'),
    ('English (native)', 'Languages'),
    ('Basket weaving', OTHER_SKILLS),
])
def test_name_decides_the_group_when_no_category_is_saved(name, expected):
    assert skill_group(name, 'unspecified') == expected


def test_names_are_matched_whole_and_ignore_case_and_spacing():
    assert skill_group('  PYTHON ') == 'Technical coding'
    assert skill_group('Going to market') == OTHER_SKILLS  # "go" only counts as the whole name.
    assert skill_group('Crust baking') == OTHER_SKILLS  # "rust" must not match inside a word.


def test_category_is_only_a_fallback():
    assert skill_group('Basket weaving', 'Soft skills') == 'Communication & leadership'
    assert skill_group('Basket weaving', 'Product Management') == 'Software & project management'
    assert skill_group('Python', 'Soft skills') == 'Technical coding'
    assert skill_group('Basket weaving', None) == OTHER_SKILLS


def test_every_registry_skill_has_a_real_group():
    ungrouped = [name for entry in REGISTRY['skills'] for name in entry['names'] if skill_group(name) == OTHER_SKILLS]
    assert ungrouped == []


def test_map_uses_exact_displayed_names():
    assert skill_groups([('Python', None), ('Basket weaving', 'Design')]) == {'Python': 'Technical coding', 'Basket weaving': 'Design'}
    assert skill_groups([]) == {}
