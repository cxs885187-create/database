from app.db import Database
from app.glossary import GLOSSARY_TRANSLATIONS, import_glossary_translations
from app.repository import VocabularyRepository


def test_glossary_translation_import_updates_only_known_words(tmp_path):
    repository = VocabularyRepository(Database(tmp_path / 'glossary.sqlite3'))
    repository.upsert_entries([
        {'word': 'debug', 'count': 1},
        {'word': 'unlisted', 'count': 1},
    ], 'seed')
    result = import_glossary_translations(repository, {'debug': GLOSSARY_TRANSLATIONS['debug']})
    assert result == {'matched': 1, 'updated': 1, 'missing': []}
    assert repository.lookup(['debug'])['debug']['definition_zh'] == '调试'
    assert repository.lookup(['unlisted'])['unlisted']['definition_zh'] is None


def test_glossary_mapping_contains_v03_seed_terms():
    required = {
        'debug', 'case-sensitive', 'bitwiseoperator', 'deepcopy', 'assignment',
        'arithmeticoperator', 'addition', 'alias', 'argument', 'associativity',
        'backslash', 'binary', 'bit', 'bitwiseAND', 'bitwiseNOT', 'bitwiseOR',
        'bitwiseXOR', 'Booleanoperator', 'and', 'built-infunction', 'collection',
    }
    assert required <= set(GLOSSARY_TRANSLATIONS)
