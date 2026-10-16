"""Register (or update) the bot's slash commands with Discord.

    python scripts/register_discord_commands.py                 # everywhere (can take a few minutes to show up)
    python scripts/register_discord_commands.py --guild <id>    # one server, instantly (for testing)
    python scripts/register_discord_commands.py --guild <id> --clear   # remove a test server's copy

Needs DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN (environment or the repo's .env).
Run it again whenever discord_bot/commands.py changes.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / '.env')

from discord_bot import client  # noqa: E402
from discord_bot.commands import COMMANDS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--guild', help='Register in this server only (shows up instantly)')
    parser.add_argument('--clear', action='store_true', help='Remove the commands instead')
    args = parser.parse_args()

    try:
        result = client.overwrite_commands([] if args.clear else COMMANDS, guild_id=args.guild)
    except client.DiscordError as error:
        sys.exit(f'Failed: {error}')
    where = f'server {args.guild}' if args.guild else 'all servers'
    print(f"{len(result)} command(s) registered for {where}: {', '.join('/' + c['name'] for c in result) or '-'}")


if __name__ == '__main__':
    main()
