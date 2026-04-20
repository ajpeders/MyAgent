from core.session_store import SessionState


def test_session_state_defaults():
    state = SessionState(session_id="test", user_id="u1")
    assert state.mail_engine is None
    assert state.imap_accounts is None


def test_session_state_stores_mail_engine():
    state = SessionState(session_id="test", user_id="u1")
    state.mail_engine = {"inbox": [], "page": 0, "model": "test", "page_size": 20, "account": ""}
    assert state.mail_engine["page"] == 0


def test_session_state_stores_imap_accounts():
    state = SessionState(session_id="test", user_id="u1")
    state.imap_accounts = [
        {"name": "Gmail", "host": "imap.gmail.com", "port": 993, "user": "me@gmail.com", "password": "secret"},
    ]
    assert state.imap_accounts[0]["password"] == "secret"
