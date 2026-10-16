"""Discord slash commands: request signatures, class per channel, CR checks, /setup and replies."""
import json
import time

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

import db_fetch
import links
import main
from conftest import CLASS_ID, FakeRepo, exam_row
from discord_bot import client as discord
from discord_bot import interactions
from discord_bot.commands import COMMANDS

SIGNING_KEY = SigningKey.generate()
GUILD, CHANNEL, NEW_CHANNEL, USER, CR_ROLE = '900000000000000001', '900000000000000002', '900000000000000009', \
    '123456789012345678', '700000000000000001'
CLASS = {'id': CLASS_ID, 'name': 'CSE 22', 'discord_guild_id': GUILD, 'discord_channel_id': CHANNEL,
         'cr_role_id': None, 'view_key': '6f1d1d4e-1111-4111-8111-111111111111', 'auto_updates': True,
         'archived_at': None}
MANAGE_CHANNELS = str(1 << 4)
MEMBER = '1024'  # View Channel only


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setenv('DISCORD_PUBLIC_KEY', SIGNING_KEY.verify_key.encode().hex())
    monkeypatch.setenv('DISCORD_APPLICATION_ID', '111111111111111111')
    classes = {CHANNEL: dict(CLASS)}
    monkeypatch.setattr(db_fetch, 'fetch_class_by_channel', lambda ch: classes.get(ch))
    rows = [exam_row(1, 1, 'CT 2', '2026-10-20', exam_time='10:00:00', notes_link='https://drive.example/n')]
    monkeypatch.setattr(db_fetch, 'query_exams', FakeRepo(rows).query_exams)
    replies = []
    monkeypatch.setattr(discord, 'reply', lambda token, messages, ephemeral, components=None:
                        replies.append({'token': token, 'messages': messages, 'ephemeral': ephemeral,
                                        'components': components}))
    test_client = TestClient(main.app)
    test_client.replies = replies
    test_client.classes = classes
    return test_client


def signed(body: dict, *, key=SIGNING_KEY, timestamp=None):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) if timestamp is None else timestamp)
    signature = key.sign(ts.encode() + raw).signature.hex()
    return {'content': raw, 'headers': {'X-Signature-Ed25519': signature, 'X-Signature-Timestamp': ts,
                                        'Content-Type': 'application/json'}}


def command(name, *, options=None, permissions=MEMBER, roles=(), channel=CHANNEL, channel_obj=None, guild=GUILD):
    body = {'type': 2, 'token': 'itoken', 'guild_id': guild, 'channel_id': channel,
            'data': {'name': name, 'options': [{'name': k, 'value': v} for k, v in (options or {}).items()]},
            'member': {'user': {'id': USER}, 'permissions': permissions, 'roles': list(roles)}}
    if channel_obj:
        body['channel'] = channel_obj
    return body


def run(bot, name, **kwargs):
    response = bot.post('/discord/interactions', **signed(command(name, **kwargs)))
    assert response.status_code == 200, response.text
    assert response.json() == {'type': 5, 'data': {'flags': 64}}  # "thinking…", only the user sees it
    return bot.replies[-1]


# --- Request verification --------------------------------------------------------
def test_ping(bot):
    assert bot.post('/discord/interactions', **signed({'type': 1})).json() == {'type': 1}


def test_bad_signature_is_rejected(bot):
    assert bot.post('/discord/interactions', **signed({'type': 1}, key=SigningKey.generate())).status_code == 401
    req = signed({'type': 1})
    req['headers']['X-Signature-Ed25519'] = 'zz'
    assert bot.post('/discord/interactions', **req).status_code == 401
    assert bot.post('/discord/interactions', json={'type': 1}).status_code == 401


def test_old_timestamp_is_rejected(bot):
    assert bot.post('/discord/interactions', **signed({'type': 1}, timestamp=int(time.time()) - 3600)).status_code == 401


def test_body_tampering_is_rejected(bot):
    req = signed({'type': 1})
    req['content'] = req['content'].replace(b'1', b'2')
    assert bot.post('/discord/interactions', **req).status_code == 401


# --- Commands -------------------------------------------------------------------
def test_commands_are_registered_for_servers_only():
    names = {c['name'] for c in COMMANDS}
    assert {'setup', 'next-week-update', 'this-week-update', 'next-exam-day-update', 'next-exam-notes', 'exams',
            'manage', 'ask'} == names
    assert all(c['contexts'] == [0] for c in COMMANDS)
    assert next(c for c in COMMANDS if c['name'] == 'setup')['default_member_permissions'] == MANAGE_CHANNELS


UPDATES = [
    ('next-week-update', "Next week's exams"), ('this-week-update', 'exams'),
    ('next-exam-day-update', 'Next exam day'), ('next-exam-notes', 'Notes for the next exam day'),
]


@pytest.fixture
def channel_posts(monkeypatch):
    interactions._recent_posts.clear()
    posts = []
    monkeypatch.setattr(discord, 'post_messages', lambda channel, messages: posts.append((channel, messages)))
    return posts


@pytest.mark.parametrize('name,expect', UPDATES)
def test_student_sees_the_update_privately(bot, channel_posts, name, expect):
    reply = run(bot, name)
    assert reply['ephemeral'] and reply['token'] == 'itoken'
    assert expect in '\n'.join(reply['messages'])
    assert channel_posts == []


@pytest.mark.parametrize('name,expect', UPDATES)
def test_cr_posts_the_update_for_everyone(bot, channel_posts, name, expect):
    reply = run(bot, name, permissions=MANAGE_CHANNELS)
    assert channel_posts and channel_posts[0][0] == CHANNEL
    assert expect in '\n'.join(channel_posts[0][1])
    assert 'Posted in the channel for everyone' in reply['messages'][0]


def test_cr_role_member_posts_too(bot, channel_posts):
    bot.classes[CHANNEL]['cr_role_id'] = CR_ROLE
    run(bot, 'next-week-update', roles=(CR_ROLE,))
    assert len(channel_posts) == 1


def test_cr_post_in_a_thread_goes_to_that_thread(bot, channel_posts):
    thread = '900000000000000077'
    run(bot, 'next-week-update', permissions=MANAGE_CHANNELS, channel=thread,
        channel_obj={'id': thread, 'type': 11, 'parent_id': CHANNEL})
    assert channel_posts[0][0] == thread


def test_cr_double_run_posts_once(bot, channel_posts):
    run(bot, 'next-week-update', permissions=MANAGE_CHANNELS)
    reply = run(bot, 'next-week-update', permissions=MANAGE_CHANNELS)
    assert len(channel_posts) == 1 and 'just posted' in reply['messages'][0]


def test_cr_post_without_channel_access_still_shows_the_update(bot, monkeypatch):
    interactions._recent_posts.clear()

    def denied(channel, messages):
        raise discord.DiscordError('403', status=403, code=discord.MISSING_ACCESS)
    monkeypatch.setattr(discord, 'post_messages', denied)
    reply = run(bot, 'next-week-update', permissions=MANAGE_CHANNELS)
    assert 'Send Messages' in reply['messages'][0] and "Next week's exams" in '\n'.join(reply['messages'])


def test_unconfigured_channel(bot):
    reply = run(bot, 'next-week-update', channel=NEW_CHANNEL)
    assert '/setup' in reply['messages'][0]


def test_thread_uses_its_channel_class(bot):
    reply = run(bot, 'exams', channel='900000000000000077',
                channel_obj={'id': '900000000000000077', 'type': 11, 'parent_id': CHANNEL})
    assert reply['components'][0]['components'][0]['url'] == f"https://board.example/c/{CLASS['view_key']}"


def test_exams_link(bot):
    reply = run(bot, 'exams')
    button = reply['components'][0]['components'][0]
    assert button['style'] == 5 and button['url'].endswith(CLASS['view_key'])


def test_manage_is_for_crs_only(bot):
    reply = run(bot, 'manage')
    assert 'Only CRs' in reply['messages'][0] and reply['components'] is None


@pytest.mark.parametrize('permissions,roles,class_role', [
    (MANAGE_CHANNELS, (), None), (str(1 << 3), (), None), (MEMBER, (CR_ROLE,), CR_ROLE),
])
def test_manage_gives_cr_a_private_editor_link(bot, permissions, roles, class_role):
    bot.classes[CHANNEL]['cr_role_id'] = class_role
    reply = run(bot, 'manage', permissions=permissions, roles=roles)
    url = reply['components'][0]['components'][0]['url']
    assert reply['ephemeral'] and url.startswith('https://board.example/cr/#t=')
    claims = links.read_editor_token(url.split('#t=')[1])
    assert claims.class_id == CLASS_ID and claims.user_id == USER


def test_cr_role_of_another_class_does_not_count(bot):
    bot.classes[CHANNEL]['cr_role_id'] = CR_ROLE
    reply = run(bot, 'manage', roles=('700000000000000002',))
    assert 'Only CRs' in reply['messages'][0]


def test_ask_is_scoped_to_the_channel_class(bot, monkeypatch):
    asked = []
    monkeypatch.setattr(interactions, 'answer', lambda q, class_id: asked.append((q, class_id))
                        or type('R', (), {'messages': ['ok']})())
    assert run(bot, 'ask', options={'question': 'next CT?'})['messages'] == ['ok']
    assert asked == [('next CT?', CLASS_ID)]


def test_database_outage_is_reported(bot, monkeypatch):
    def down(ch):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'fetch_class_by_channel', down)
    assert "couldn't reach the exam database" in run(bot, 'next-week-update')['messages'][0]


def test_dm_is_refused(bot):
    assert "class's channel" in run(bot, 'next-week-update', guild=None)['messages'][0]


# --- /setup ----------------------------------------------------------------------
@pytest.fixture
def writes(monkeypatch):
    log = []

    def create(**kw):
        log.append(('create', kw))
        return {**CLASS, 'id': 5, 'name': kw['name'], 'discord_channel_id': kw['channel_id'], 'cr_role_id': kw['cr_role_id']}

    def update(cid, changes, only_if_unlinked=False):
        log.append(('update', cid, changes, only_if_unlinked))
        return {**CLASS, 'id': cid, **changes}
    monkeypatch.setattr(db_fetch, 'create_class', create)
    monkeypatch.setattr(db_fetch, 'update_class', update)
    monkeypatch.setattr(db_fetch, 'fetch_unlinked_classes', lambda: [{**CLASS, 'id': 3, 'discord_channel_id': None}])
    return log


def test_setup_needs_manage_channels(bot, writes):
    reply = run(bot, 'setup', channel=NEW_CHANNEL, options={'name': 'EEE 22'})
    assert 'Manage Channels' in reply['messages'][0] and writes == []


def test_setup_creates_a_class_for_the_channel(bot, writes):
    reply = run(bot, 'setup', channel=NEW_CHANNEL, permissions=MANAGE_CHANNELS,
                options={'name': '  EEE   22 ', 'cr_role': CR_ROLE})
    assert writes == [('create', {'name': 'EEE 22', 'guild_id': GUILD, 'channel_id': NEW_CHANNEL, 'cr_role_id': CR_ROLE})]
    text = reply['messages'][0]
    assert '**EEE 22**' in text and 'Friday at 18:00' in text and f'<@&{CR_ROLE}>' in text


def test_setup_again_updates_the_class(bot, writes):
    run(bot, 'setup', permissions=MANAGE_CHANNELS, options={'name': 'CSE 22 A', 'auto_updates': False})
    assert writes == [('update', CLASS_ID, {'name': 'CSE 22 A', 'auto_updates': False}, False)]


def test_setup_can_claim_the_earlier_data(bot, writes):
    reply = run(bot, 'setup', channel=NEW_CHANNEL, permissions=MANAGE_CHANNELS,
                options={'name': 'CSE 22', 'use_existing_data': True})
    assert writes == [('update', 3, {'name': 'CSE 22', 'discord_guild_id': GUILD, 'discord_channel_id': NEW_CHANNEL}, True)]
    assert 'earlier courses' in reply['messages'][0]


def test_setup_claim_when_nothing_is_waiting(bot, writes, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_unlinked_classes', lambda: [])
    reply = run(bot, 'setup', channel=NEW_CHANNEL, permissions=MANAGE_CHANNELS,
                options={'name': 'CSE 22', 'use_existing_data': True})
    assert 'no earlier data' in reply['messages'][0] and writes == []


# --- Discord client ----------------------------------------------------------------
def test_messages_never_ping_anyone():
    payload = discord.message_payload('@everyone exam!')
    assert payload['allowed_mentions'] == {'parse': []}
