"""Fill missing Chinese meanings with the model, from the command line.

    .venv\\Scripts\\python.exe -m app.fill_translations
    .venv\\Scripts\\python.exe -m app.fill_translations --words skill,shot --limit 20
    .venv\\Scripts\\python.exe -m app.fill_translations --words able,address --overwrite
"""
import argparse
import asyncio

from .config import Settings
from .db import Database
from .deepseek import DeepSeekClient, ModelUnavailable
from .repository import VocabularyRepository
from .translate import TranslationService


async def run(args):
    settings = Settings.from_env()
    repository = VocabularyRepository(Database(args.database or settings.database_path))
    service = TranslationService(repository,DeepSeekClient(settings))
    if not service.available:
        raise ModelUnavailable('Set DEEPSEEK_API_KEY to generate Chinese meanings')
    words = [word.strip() for word in args.words.split(',') if word.strip()] if args.words else None
    return await service.fill(words,args.limit,args.overwrite)


def main():
    parser = argparse.ArgumentParser(description='Fill empty Chinese meanings from the DeepSeek model.')
    parser.add_argument('--database')
    parser.add_argument('--words',help='Comma-separated words; default is every word without a meaning')
    parser.add_argument('--limit',type=int,default=None)
    parser.add_argument('--overwrite',action='store_true',help='Re-translate the named words even when a meaning exists')
    print(asyncio.run(run(parser.parse_args())))


if __name__ == '__main__':
    main()
