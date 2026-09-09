from __future__ import annotations

from datetime import date

from app.agent.parser import parse_message
from app.agent.schemas import ConfigurePlace


class MustNotBeCalled:
    def call(self, text, system_instruction):
        raise AssertionError("private command was sent to the model")


def test_precise_saved_place_is_parsed_locally_without_model_disclosure():
    result = parse_message(
        "my home is 42 Private Road, Pilani",
        MustNotBeCalled(),
        today=date(2026, 9, 10),
    )
    assert result.actions == [ConfigurePlace("home", "42 Private Road, Pilani")]


def test_calendar_connection_and_confirmation_commands_stay_local():
    connect = parse_message("connect my google calendar", MustNotBeCalled())
    confirm = parse_message("confirm a1b2c3", MustNotBeCalled())
    assert type(connect.actions[0]).__name__ == "ConnectCalendar"
    assert confirm.actions[0].proposal_id == "A1B2C3"
