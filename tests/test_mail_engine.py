import json
from unittest.mock import patch

from core.actions.action import Action, ActionType, Plan
from core.mail_engine import MailEngine


FAKE_EMAILS = [
    {
        "uid": 101,
        "from": "alice@test.com",
        "subject": "Hello",
        "date": "2026-04-19",
        "body": "Hi there",
        "account": "Gmail",
    },
    {
        "uid": 102,
        "from": "bob@test.com",
        "subject": "Meeting",
        "date": "2026-04-19",
        "body": "At 3pm",
        "account": "Gmail",
    },
    {
        "uid": 103,
        "from": "carol@test.com",
        "subject": "Promo",
        "date": "2026-04-19",
        "body": "Buy now",
        "account": "Yahoo",
    },
]


class TestDisplay:
    def test_display_empty_inbox(self):
        engine = MailEngine(model="test")
        assert engine.display() == "[mail] Inbox is empty."

    def test_display_shows_numbered_list(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]
        output = engine.display()
        assert "1." in output
        assert "alice@test.com" in output
        assert "2." in output
        assert "3." in output

    def test_display_shows_recommendations(self):
        engine = MailEngine(model="test")
        emails = [email.copy() for email in FAKE_EMAILS]
        emails[0]["recommendation"] = "delete"
        emails[1]["recommendation"] = "keep"
        engine.inbox = emails
        output = engine.display()
        assert "[delete]" in output
        assert "[keep]" in output

    def test_display_email_by_page_index(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]
        output = engine.display_email(1)
        assert "alice@test.com" in output
        assert "Hello" in output
        assert "Hi there" in output

    def test_display_email_invalid_index(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]
        output = engine.display_email(99)
        assert "invalid" in output.lower()


class TestState:
    def test_remove_by_indices(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]
        engine.remove_by_indices([1, 3])
        assert len(engine.inbox) == 1
        assert engine.inbox[0]["subject"] == "Meeting"

    def test_remove_by_indices_out_of_range_skipped(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]
        engine.remove_by_indices([1, 99])
        assert len(engine.inbox) == 2


class TestPagination:
    def _engine_with_emails(self, count: int, page_size: int = 3) -> MailEngine:
        engine = MailEngine(model="test", page_size=page_size)
        engine.inbox = [
            {
                "uid": i,
                "from": f"user{i}@test.com",
                "subject": f"Email {i}",
                "date": "2026-04-19",
                "body": f"Body {i}",
                "account": "Gmail",
            }
            for i in range(1, count + 1)
        ]
        return engine

    def test_first_page_shows_page_size_emails(self):
        engine = self._engine_with_emails(10, page_size=3)
        page = engine.current_page()
        assert len(page) == 3
        assert page[0]["subject"] == "Email 1"

    def test_next_page(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.next_page()
        assert engine.page == 1
        page = engine.current_page()
        assert page[0]["subject"] == "Email 4"

    def test_prev_page_at_start_stays(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.prev_page()
        assert engine.page == 0

    def test_next_page_at_end_stays(self):
        engine = self._engine_with_emails(10, page_size=3)
        for _ in range(20):
            engine.next_page()
        assert engine.page == engine.total_pages - 1

    def test_go_to_page(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.go_to_page(3)
        assert engine.page == 2

    def test_display_shows_page_header_when_multiple_pages(self):
        engine = self._engine_with_emails(10, page_size=3)
        output = engine.display()
        assert "Page 1/" in output
        assert "Showing 1-3 of 10" in output

    def test_display_no_page_header_single_page(self):
        engine = self._engine_with_emails(3, page_size=20)
        output = engine.display()
        assert "Page" not in output

    def test_indices_are_page_relative(self):
        engine = self._engine_with_emails(10, page_size=3)
        engine.next_page()
        assert engine.display_email(1).startswith("FROM: user4@test.com")
        assert engine.get_uids_for_indices([1]) == [4]


class TestSerialization:
    def test_to_dict_and_back(self):
        engine = MailEngine(model="qwen3:8b", page_size=5)
        engine.inbox = [FAKE_EMAILS[0].copy()]
        engine.inbox[0]["recommendation"] = "keep"
        engine.account = "Gmail"
        engine.page = 2

        data = engine.to_dict()
        restored = MailEngine.from_dict(data)

        assert restored.model == "qwen3:8b"
        assert restored.page_size == 5
        assert restored.page == 2
        assert restored.account == "Gmail"
        assert len(restored.inbox) == 1
        assert restored.inbox[0]["recommendation"] == "keep"

    def test_to_dict_is_json_serializable(self):
        engine = MailEngine(model="test")
        engine.inbox = [FAKE_EMAILS[0].copy()]
        serialized = json.dumps(engine.to_dict())
        assert isinstance(serialized, str)


class TestRecommend:
    def test_recommend_tags_emails(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        llm_response = json.dumps({
            "recommendations": [
                {"index": 1, "action": "keep"},
                {"index": 2, "action": "keep"},
                {"index": 3, "action": "delete"},
            ]
        })

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = llm_response
            engine.recommend()

        assert engine.inbox[0]["recommendation"] == "keep"
        assert engine.inbox[1]["recommendation"] == "keep"
        assert engine.inbox[2]["recommendation"] == "delete"

    def test_recommend_defaults_to_keep_on_failure(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.side_effect = Exception("LLM down")
            engine.recommend()

        for email in engine.inbox:
            assert email.get("recommendation") == "keep"

    def test_recommend_defaults_to_keep_on_bad_json(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = "not json"
            engine.recommend()

        for email in engine.inbox:
            assert email.get("recommendation") == "keep"


class TestParseIntent:
    def test_parse_delete_returns_mail_move(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1, 3], folder="Trash")
        ]).model_dump_json()

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            plan = engine.parse_intent("delete 1 and 3")

        assert len(plan.actions) == 1
        assert plan.actions[0].type == ActionType.mail_move
        assert plan.actions[0].indices == [1, 3]

    def test_parse_intent_on_bad_response_returns_done(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = "garbage"
            plan = engine.parse_intent("delete 1")

        assert len(plan.actions) == 1
        assert plan.actions[0].type == ActionType.done


class TestExecute:
    def test_fetch_populates_inbox(self):
        fake = [FAKE_EMAILS[0].copy()]
        engine = MailEngine(model="test")

        with patch("core.mail_engine.mail_read_emails", return_value=fake), \
             patch("core.mail_engine.mail_refresh"), \
             patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = json.dumps({
                "recommendations": [{"index": 1, "action": "keep"}]
            })
            engine.fetch()

        assert len(engine.inbox) == 1
        assert engine.inbox[0]["subject"] == "Hello"
        assert engine.inbox[0]["recommendation"] == "keep"

    def test_execute_mail_move_removes_from_cache(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        action = Action(type=ActionType.mail_move, indices=[1], folder="Trash")

        with patch("core.mail_engine.mail_move_by_uids", return_value=1):
            result = engine.execute(action)

        assert len(engine.inbox) == 2
        assert "1" in result
        assert engine.inbox[0]["subject"] == "Meeting"

    def test_execute_answer_returns_email_body(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        action = Action(type=ActionType.answer, indices=[2])
        result = engine.execute(action)

        assert "Meeting" in result
        assert "At 3pm" in result

    def test_execute_done_returns_done_message(self):
        engine = MailEngine(model="test")
        action = Action(type=ActionType.done)
        result = engine.execute(action)
        assert "ended" in result.lower()


class TestHandle:
    def test_handle_returns_results_list(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.answer, indices=[1])
        ]).model_dump_json()

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("read 1")

        assert len(results) >= 1
        assert results[0]["type"] == "answer"
        assert "Hello" in results[0]["content"]

    def test_handle_done_returns_done_result(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        plan_json = Plan(actions=[Action(type=ActionType.done)]).model_dump_json()

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("done")

        assert any(result["type"] == "done" for result in results)

    def test_handle_mail_move_returns_confirm(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1], folder="Trash")
        ]).model_dump_json()

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("delete 1")

        assert results[0]["type"] == "confirm"
        assert results[0]["pending"] is not None

    def test_handle_redisplays_after_answer(self):
        engine = MailEngine(model="test")
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        plan_json = Plan(actions=[
            Action(type=ActionType.answer, indices=[1])
        ]).model_dump_json()

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = plan_json
            results = engine.handle("read 1")

        assert "answer" in [result["type"] for result in results]
        assert "mail_list" in [result["type"] for result in results]

    def test_handle_next_page_is_deterministic(self):
        engine = MailEngine(model="test", page_size=1)
        engine.inbox = [email.copy() for email in FAKE_EMAILS]

        with patch("core.mail_engine.default_adapter") as mock_llm:
            results = engine.handle("next")

        mock_llm.complete.assert_not_called()
        assert engine.page == 1
        assert results[0]["emails"][0]["subject"] == "Meeting"


class TestFullFlow:
    def test_fetch_recommend_delete_redisplay(self):
        fake_emails = [
            {
                "uid": 1,
                "from": "spam@test.com",
                "subject": "Buy now",
                "date": "2026-04-19",
                "body": "Promo",
                "account": "Gmail",
            },
            {
                "uid": 2,
                "from": "boss@test.com",
                "subject": "Meeting",
                "date": "2026-04-19",
                "body": "At 3pm",
                "account": "Gmail",
            },
        ]
        rec_response = json.dumps({
            "recommendations": [
                {"index": 1, "action": "delete"},
                {"index": 2, "action": "keep"},
            ]
        })
        delete_plan = Plan(actions=[
            Action(type=ActionType.mail_move, indices=[1], folder="Trash")
        ]).model_dump_json()
        engine = MailEngine(model="test")

        with patch("core.mail_engine.mail_read_emails", return_value=fake_emails), \
             patch("core.mail_engine.mail_refresh"), \
             patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = rec_response
            engine.fetch()

        assert len(engine.inbox) == 2
        assert engine.inbox[0]["recommendation"] == "delete"
        assert engine.inbox[1]["recommendation"] == "keep"

        display = engine.display()
        assert "Buy now" in display
        assert "[delete]" in display
        assert "[keep]" in display

        with patch("core.mail_engine.default_adapter") as mock_llm:
            mock_llm.complete.return_value = delete_plan
            plan = engine.parse_intent("delete 1")

        assert plan.actions[0].indices == [1]

        with patch("core.mail_engine.mail_move_by_uids", return_value=1):
            result = engine.execute(plan.actions[0])

        assert "Deleted 1" in result
        assert len(engine.inbox) == 1

        display = engine.display()
        assert "Buy now" not in display
        assert "Meeting" in display
        assert "[keep]" in display
