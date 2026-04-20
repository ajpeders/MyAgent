import json

from core.actions.action import Action, ActionType


class TestActionIndex:
    def test_action_has_indices_field(self):
        action = Action(type=ActionType.mail_move, indices=[1, 3], folder="Trash")
        assert action.indices == [1, 3]

    def test_action_indices_default_empty(self):
        action = Action(type=ActionType.mail_move, folder="Trash")
        assert action.indices == []

    def test_action_serializes_indices(self):
        action = Action(type=ActionType.mail_move, indices=[2], folder="Trash")
        data = json.loads(action.model_dump_json())
        assert data["indices"] == [2]


def test_mail_save_action_type_removed():
    assert "mail_save" not in ActionType.__members__
