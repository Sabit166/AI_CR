"""Signed editor links."""
import time

import pytest

import links


def test_round_trip():
    token = links.make_editor_token(7, '123456789012345678')
    claims = links.read_editor_token(token)
    assert claims.class_id == 7 and claims.user_id == '123456789012345678'
    assert claims.expires_at > time.time() + 11 * 3600


def test_expiry_is_configurable(monkeypatch):
    monkeypatch.setenv('EDITOR_LINK_HOURS', '1')
    token = links.make_editor_token(7, '123456789012345678', now=time.time() - 3700)
    assert links.read_editor_token(token) is None


@pytest.mark.parametrize('token', ['', 'x', 'e1.7.1.9999999999', 'e1.7.1.9999999999.sig', 'e2.7.1.9999999999.sig',
                                   'e1.x.1.9999999999.sig', 'e1.7.1.9999999999.' + 'A' * 400])
def test_garbage_is_rejected(token):
    assert links.read_editor_token(token) is None


def test_changing_the_secret_revokes_links(monkeypatch):
    token = links.make_editor_token(7, '123456789012345678')
    monkeypatch.setenv('EDITOR_LINK_SECRET', 'another-secret-another-secret-another-secret')
    assert links.read_editor_token(token) is None


def test_short_secret_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv('EDITOR_LINK_SECRET', 'short')
    with pytest.raises(links.LinksMisconfigured):
        links.make_editor_token(7, '1')


def test_urls():
    assert links.board_url('abc') == 'https://board.example/c/abc'
    assert links.editor_url('tok') == 'https://board.example/cr/#t=tok'
