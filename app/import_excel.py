"""Read historical workbooks into SQLite without modifying the original Excel files."""
import argparse
import hashlib
from pathlib import Path
import openpyxl
from .config import Settings
from .db import Database
from .repository import VocabularyRepository

def import_workbook(repository,path):
    path = Path(path)
    workbook = openpyxl.load_workbook(path,read_only=True,data_only=True)
    try:
        sheet = workbook['Vocabulary'] if 'Vocabulary' in workbook.sheetnames else workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        header_index = next(i for i,row in enumerate(rows) if any(str(v).strip().lower() in {'word','words'} for v in row))
        headers = [str(v or '').strip().lower() for v in rows[header_index]]
        mappings = {'word':'word','words':'word','part of speech':'part_of_speech',
                    'meaning':'definition_en','example sentence':'example_sentences','topic':'semantic_tag'}
        entries = []
        for row in rows[header_index+1:]:
            values = {mappings[key]:str(row[i]) for i,key in enumerate(headers) if key in mappings and i<len(row) and row[i] is not None}
            if not values.get('word'):
                continue
            values['count']=1
            for key in ('part_of_speech','example_sentences'):
                if values.get(key):
                    values[key]=[values[key]]
            values['usage_contexts']=['Imported from historical Excel vocabulary']
            entries.append(values)
        source_id = 'excel_'+hashlib.sha256(path.read_bytes()).hexdigest()[:32]
        return repository.upsert_entries(entries,source_id)
    finally:
        workbook.close()

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--database')
    args = parser.parse_args()
    repository = VocabularyRepository(Database(args.database or Settings.from_env().database_path))
    result = import_workbook(repository,args.path)
    print(f"Imported {result['success']} records; {result['duplicates']} retries skipped; {result['failed']} rejected.")
