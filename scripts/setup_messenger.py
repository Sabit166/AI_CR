"""Publish the ice breakers in messenger_profile.py to the Facebook Page.

    python scripts/setup_messenger.py            # apply
    python scripts/setup_messenger.py --show     # print what Facebook currently has

Needs PAGE_ACCESS_TOKEN (read from the environment or the repo's .env). Run it
again whenever ICE_BREAKERS changes. In the Meta app dashboard the webhook must
also be subscribed to the `messaging_postbacks` field, or taps never reach the bot.
"""
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / '.env')

from messenger_profile import profile_payload  # noqa: E402

GRAPH = 'https://graph.facebook.com/v23.0/me/messenger_profile'


def call(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b'{}')
    except HTTPError as error:
        sys.exit(f'Facebook returned {error.code}: {error.read().decode(errors="replace")}')


def main() -> None:
    token = os.getenv('PAGE_ACCESS_TOKEN')
    if not token:
        sys.exit('PAGE_ACCESS_TOKEN is not set (add it to .env or the environment).')
    if '--show' in sys.argv:
        print(json.dumps(call('GET', f'{GRAPH}?fields=ice_breakers&access_token={token}'), indent=2))
        return
    print(call('POST', f'{GRAPH}?access_token={token}', profile_payload()))
    print('Ice breakers updated. Open a new chat with the Page in the Messenger app to see them.')


if __name__ == '__main__':
    main()
