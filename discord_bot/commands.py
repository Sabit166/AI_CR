"""Slash command definitions. Register them with scripts/register_discord_commands.py."""
from __future__ import annotations

MANAGE_CHANNELS = 1 << 4
GUILD_ONLY = {'contexts': [0], 'integration_types': [0]}  # server channels only, server installs only

STRING, BOOLEAN, ROLE = 3, 5, 8

COMMANDS: list[dict] = [
    {
        'name': 'setup',
        'description': 'Make this channel a class (or update its name / CR role). Needs Manage Channels.',
        'default_member_permissions': str(MANAGE_CHANNELS),
        'options': [
            {'type': STRING, 'name': 'name', 'description': 'Class name, e.g. CSE 4th year, Section A',
             'required': True, 'min_length': 2, 'max_length': 100},
            {'type': ROLE, 'name': 'cr_role', 'description': 'Role whose members are CRs (Manage Channels always counts)',
             'required': False},
            {'type': BOOLEAN, 'name': 'use_existing_data',
             'description': 'Link the courses and exams saved before the Discord bot to this channel', 'required': False},
            {'type': BOOLEAN, 'name': 'auto_updates',
             'description': 'Friday next-week update and day-before reminders (default on)', 'required': False},
        ],
    },
    # The four updates. Run by a CR, the update is posted in the channel for everyone;
    # run by anyone else, only they see it.
    {'name': 'next-week-update', 'description': "Next week's exams (Sunday–Thursday). CRs: posts it for everyone"},
    {'name': 'this-week-update', 'description': "This week's remaining exams. CRs: posts it for everyone"},
    {'name': 'next-exam-day-update', 'description': 'Every exam on the next exam day, with times. CRs: posts it for everyone'},
    {'name': 'next-exam-notes', 'description': 'Notes links for the next exam day. CRs: posts it for everyone'},
    {'name': 'exams', 'description': 'Open the list of upcoming exams for this class'},
    {'name': 'manage', 'description': 'CRs: open the editor for this class (link only you can see)'},
    {
        'name': 'ask',
        'description': 'Ask about exams in your own words (e.g. syllabus of the next CT of a course)',
        'options': [
            {'type': STRING, 'name': 'question', 'description': 'e.g. When is the next CT of CSE-415?',
             'required': True, 'max_length': 300},
        ],
    },
]

for _command in COMMANDS:
    _command.update(GUILD_ONLY)
