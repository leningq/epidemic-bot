import pytest

from epidemic.utils.parse import (
    InfectCommand,
    SkillCommand,
    TargetRef,
    parse_duration,
    parse_infect,
    parse_skill_command,
    parse_target_token,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("++зз 5", SkillCommand("++", "infect", 5)),
        ("+иммун", SkillCommand("+", "immunity", None)),
        ("+Иммунитет 3", SkillCommand("+", "immunity", 3)),
        ("-сб 3", SkillCommand("-", "security", 3)),
        ("+патоген", SkillCommand("+", "pathogens", None)),
        ("+пат 2", SkillCommand("+", "pathogens", 2)),
        ("++квала", SkillCommand("++", "science", None)),
        ("++летальность 10", SkillCommand("++", "lethality", 10)),
        ("зз", None),
        ("+лаб", None),
        ("+++зз", None),
        ("++зз пять", None),
    ],
)
def test_parse_skill_command(text, expected):
    assert parse_skill_command(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("заразить @user_one", InfectCommand(None, 1, TargetRef(username="user_one"))),
        ("заразить @user_one 3", InfectCommand(None, 3, TargetRef(username="user_one"))),
        ("заразить 3 @user_one", InfectCommand(None, 3, TargetRef(username="user_one"))),
        (".заразить 123456789 2", InfectCommand(None, 2, TargetRef(user_id=123456789))),
        ("Заразить +", InfectCommand("stronger", 1, None)),
        ("заразить =", InfectCommand("equal", 1, None)),
        ("заразить слабее 4", InfectCommand("weaker", 4, None)),
        ("заразить р", InfectCommand("random", 1, None)),
        ("заразить", InfectCommand(None, 1, None)),
        ("заразить 5", InfectCommand(None, 5, None)),
        ("заразить 15", InfectCommand(None, 10, None)),
        ("заразить tg://openmessage?user_id=123456", InfectCommand(None, 1, TargetRef(user_id=123456))),
        ("заразить https://t.me/some_user", InfectCommand(None, 1, TargetRef(username="some_user"))),
        ("заразить васю", None),
        ("заразить + @user_one", None),
        ("заразитьвсех", None),
        ("привет", None),
    ],
)
def test_parse_infect(text, expected):
    assert parse_infect(text) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("@durov", TargetRef(username="durov")),
        ("t.me/durov", TargetRef(username="durov")),
        ("tg://user?id=777000", TargetRef(user_id=777000)),
        ("777000", TargetRef(user_id=777000)),
        ("@ab", None),
        ("привет", None),
    ],
)
def test_parse_target_token(token, expected):
    assert parse_target_token(token) == expected


def test_parse_duration():
    assert parse_duration("30m") == 1800
    assert parse_duration("12h") == 43200
    assert parse_duration("7д") == 7 * 86400
    assert parse_duration("7") is None
    assert parse_duration("") is None
