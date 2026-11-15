"""Editable prompts are loaded per request, never cached in worker processes."""
import os
from pathlib import Path

NAMES = frozenset({
    'opportunity-review', 'opportunity-review-repair', 'semantic-dedupe',
    'geography', 'geography-repair', 'product-rule-review', 'legacy-keyword-review',
})
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / '.ai-settings'


def load_prompt(name: str) -> str:
    if name not in NAMES:
        raise ValueError('unknown_ai_prompt')
    directory = Path(os.environ.get('AI_SETTINGS_DIR') or DEFAULT_DIRECTORY)
    try:
        # A finite read prevents an accidentally huge file becoming an unbounded request.
        with (directory / f'{name}.md').open('rb') as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise ValueError('ai_prompt_too_large')
        content = data.decode('utf-8-sig').strip()
    except (OSError, UnicodeError):
        raise ValueError(f'ai_prompt_unavailable:{name}') from None
    if not content:
        raise ValueError(f'ai_prompt_empty:{name}')
    return content
