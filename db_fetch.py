from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
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
    return fetch_exams()


def fetch_exams(
    select_columns: list[str] | None = None,
    filters: dict[str, dict] | None = None,
    order: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Generalized Exams fetch. `filters` maps a column name to a spec dict:
      {"op": "eq",    "value": "CSE-415"}                          -> column=eq.CSE-415
      {"op": "in",    "values": ["CSE-415", "CSE-401"]}            -> column=in.(CSE-415,CSE-401)
      {"op": "range", "from": "...", "to": "..."}                  -> column=gte.from & column=lte.to
      {"op": "gte",   "value": "..."}                              -> column=gte.value
      {"op": "lte",   "value": "..."}                              -> column=lte.value

    Multiple columns in `filters` are combined with AND automatically (PostgREST default).
    """
    supabase_url = _load_env_value('SUPABASE_URL')
    supabase_api_key = _load_env_value('SUPABASE_API_KEY')

    if not supabase_url or not supabase_api_key:
        raise RuntimeError('SUPABASE_URL and SUPABASE_API_KEY must be set')

    query_params: list[tuple[str, str]] = [
        ('select', 'Course Code,Course Title,Course Teacher,Course Section,Exam Type,Exam Day,Exam Date,Syllabus,Exam Notes Drive Link' if not select_columns else ','.join(select_columns)),
    ]

    if filters:
        for column, spec in filters.items():
            op = spec.get('op')
            if op == 'eq':
                query_params.append((column, f"eq.{spec['value']}"))
            elif op == 'in':
                values = ','.join(spec['values'])
                query_params.append((column, f"in.({values})"))
            elif op == 'range':
                query_params.append((column, f"gte.{spec['from']}"))
                query_params.append((column, f"lte.{spec['to']}"))
            elif op == 'gte':
                query_params.append((column, f"gte.{spec['value']}"))
            elif op == 'lte':
                query_params.append((column, f"lte.{spec['value']}"))
            else:
                raise RuntimeError(f"Unsupported filter operator: {op!r}")

    if order:
        query_params.append(('order', order))
    if limit is not None:
        query_params.append(('limit', str(limit)))

    endpoint = f"{supabase_url.rstrip('/')}/Exams?{urlencode(query_params, quote_via=quote, safe=',*()')}"
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


def fetch_exam_column_values(column: str) -> list[str]:
    rows = fetch_exams(select_columns=[column])
    values = [row[column] for row in rows if row.get(column) is not None]
    return list(dict.fromkeys(values))


def create_exam(payload: dict) -> dict:
    return _request_json('POST', 'Exams', payload)


def update_exam(exam_id: int, payload: dict) -> dict:
    return _request_json('PATCH', f'Exams?id=eq.{exam_id}', payload)


def delete_exam(exam_id: int) -> dict:
    return _request_json('DELETE', f'Exams?id=eq.{exam_id}')


def _request_json(method: str, path: str, payload: dict | None = None) -> dict:
    supabase_url = _load_env_value('SUPABASE_URL')
    supabase_api_key = _load_env_value('SUPABASE_API_KEY')

    if not supabase_url or not supabase_api_key:
        raise RuntimeError('SUPABASE_URL and SUPABASE_API_KEY must be set')

    endpoint = f"{supabase_url.rstrip('/')}/{path.lstrip('/')}"
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    headers = {
        'apikey': supabase_api_key,
        'Authorization': f'Bearer {supabase_api_key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    request = Request(endpoint, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=15) as response:
            response_body = response.read().decode('utf-8')
    except HTTPError as error:
        raise RuntimeError(f'Failed to {method.lower()} Exams record: {error.code} {error.reason}') from error
    except URLError as error:
        raise RuntimeError(f'Failed to reach Supabase: {error.reason}') from error

    if not response_body:
        return {"status": "ok"}

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return {"status": "ok", "raw": response_body}

    if isinstance(parsed, dict):
        return parsed

    return {"data": parsed}