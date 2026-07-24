from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _load_env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    env_path = Path(__file__).with_name('.env')
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, raw_value = line.split('=', 1)
        if key.strip() == name:
            return raw_value.strip().strip('"').strip("'")

    return None


def fetch_all_exams() -> list[dict]:
    supabase_url = _load_env_value('SUPABASE_URL')
    supabase_api_key = _load_env_value('SUPABASE_API_KEY')

    if not supabase_url or not supabase_api_key:
        raise RuntimeError('SUPABASE_URL and SUPABASE_API_KEY must be set')

    endpoint = f"{supabase_url.rstrip('/')}/Exams?select=*"
    request = Request(
        endpoint,
        headers={
            'apikey': supabase_api_key,
            'Authorization': f'Bearer {supabase_api_key}',
            'Accept': 'application/json',
        },
        method='GET',
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read().decode('utf-8')
    except HTTPError as error:
        raise RuntimeError(f'Failed to fetch Exams records: {error.code} {error.reason}') from error
    except URLError as error:
        raise RuntimeError(f'Failed to reach Supabase: {error.reason}') from error

    data = json.loads(payload)
    if not isinstance(data, list):
        raise RuntimeError('Unexpected response format from Supabase')

    return data