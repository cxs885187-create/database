"""Environment-backed configuration. Secrets never enter API responses."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MODEL_ALIASES = {'deepseekapiv41flash': 'deepseek-flash', 'deepseek-flash': 'deepseek-flash'}

@dataclass(frozen=True)
class Settings:
    database_path: Path = field(default_factory=lambda: ROOT / 'data' / 'vocabulary.sqlite3')
    deepseek_api_key: str = field(default='', repr=False)
    deepseek_base_url: str = 'https://api.deepseek.com/v1'
    deepseek_model_alias: str = 'deepseekapiv41flash'
    deepseek_temperature: float = 0.3
    spacy_model: str = 'en_core_web_sm'
    dictionary_enabled: bool = True
    daily_new_limit: int = 10
    session_ttl_seconds: int = 1800

    @property
    def deepseek_model(self):
        return MODEL_ALIASES.get(self.deepseek_model_alias.lower(), self.deepseek_model_alias)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / '.env', override=False)
        return cls(
            database_path=Path(os.getenv('DATABASE_PATH', str(ROOT / 'data' / 'vocabulary.sqlite3'))).resolve(),
            deepseek_api_key=os.getenv('DEEPSEEK_API_KEY', ''),
            deepseek_base_url=os.getenv('DEEPSEEK_API_BASE', 'https://api.deepseek.com/v1').rstrip('/'),
            deepseek_model_alias=os.getenv('DEEPSEEK_MODEL_ALIAS', 'deepseekapiv41flash'),
            deepseek_temperature=float(os.getenv('DEEPSEEK_TEMPERATURE', '0.3')),
            spacy_model=os.getenv('SPACY_MODEL', 'en_core_web_sm'),
            dictionary_enabled=os.getenv('DICTIONARY_ENABLED', 'true').lower() in {'true','1','yes'},
            daily_new_limit=int(os.getenv('DAILY_NEW_LIMIT','10')),
            session_ttl_seconds=int(os.getenv('SESSION_TTL_SECONDS','1800')),
        )
