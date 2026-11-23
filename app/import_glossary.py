"""Populate Chinese meanings from the supplied glossary mapping."""
import argparse

from .config import Settings
from .db import Database
from .glossary import GLOSSARY_TRANSLATIONS, import_glossary_translations
from .repository import VocabularyRepository


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database')
    args = parser.parse_args()
    repository = VocabularyRepository(Database(args.database or Settings.from_env().database_path))
    print(import_glossary_translations(repository, GLOSSARY_TRANSLATIONS))
