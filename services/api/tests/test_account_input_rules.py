import pytest
from pydantic import ValidationError
from starlette.requests import Request

from viral_dna_api.accounts.http import (
    AccountInput,
    ActivateInput,
    LoginInput,
    MemberInput,
    PasswordInput,
    SetupInput,
    UserLoginInput,
    account_validation_error,
    local_setup_allowed,
)
from viral_dna_api.accounts.repository import (
    AccountError,
    password_hash,
    password_matches,
    username_key,
)

SETUP = {
    "kind": "enterprise",
    "name": "测试企业",
    "username": "13800000001",
    "display_name": "负责人",
    "admin_password": "12345678",
    "owner_password": "abcdefgh",
    "confirm_legacy_ownership": True,
}


def test_setup_has_no_initialization_code_and_accepts_eight_character_passwords():
    value = SetupInput.model_validate(SETUP)
    assert "setup_token" not in SetupInput.model_fields
    assert value.admin_password.get_secret_value() == "12345678"
    assert password_matches("12345678", password_hash("12345678"))
    with pytest.raises(AccountError, match="8–128"):
        password_hash("1234567")


@pytest.mark.parametrize(
    "phone",
    [
        "owner",
        "admin",
        "1380000000",
        "138000000001",
        "12800000001",
        "+8613800000001",
        "138 0000 0001",
        "１３８０００００００１",
    ],
)
def test_front_login_account_creation_and_invites_reject_non_mobile_numbers(phone):
    for model, payload in [
        (UserLoginInput, {"username": phone, "password": "12345678"}),
        (MemberInput, {"username": phone, "display_name": "成员"}),
        (
            AccountInput,
            {"kind": "personal", "name": "个人", "username": phone, "display_name": "甲"},
        ),
        (SetupInput, {**SETUP, "username": phone}),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    with pytest.raises(AccountError, match="手机号"):
        username_key(phone)


def test_mobile_numbers_are_normalized_and_admin_login_remains_independent():
    assert username_key(" 13800000001 ") == "13800000001"
    assert UserLoginInput(username=" 13800000001 ", password="12345678").username == "13800000001"
    assert LoginInput(username="admin", password="12345678").username == "admin"


@pytest.mark.parametrize("length", [7, 8, 128, 129])
def test_password_rules_match_setup_login_activation_and_changes(length):
    password = "x" * length
    for model, payload in [
        (SetupInput, {**SETUP, "admin_password": password}),
        (SetupInput, {**SETUP, "owner_password": password}),
        (LoginInput, {"username": "admin", "password": password}),
        (UserLoginInput, {"username": "13800000001", "password": password}),
        (ActivateInput, {"token": "t" * 43, "password": password}),
        (PasswordInput, {"current_password": "12345678", "new_password": password}),
    ]:
        if 8 <= length <= 128:
            model.model_validate(payload)
        else:
            with pytest.raises(ValidationError):
                model.model_validate(payload)


def test_field_guidance_does_not_return_values_passwords_or_unknown_field_names():
    try:
        SetupInput.model_validate(
            {**SETUP, "username": "private-phone", "owner_password": "short77"}
        )
    except ValidationError as error:
        result = account_validation_error(error.errors())
        assert "手机号必须为 11 位" in str(result)
        assert "前端登录密码需要 8–128" in str(result)
        assert "private-phone" not in str(result)
        assert "short77" not in str(result)
    else:
        pytest.fail("Invalid fields unexpectedly passed")
    result = account_validation_error(
        [{"loc": ("body", "secret-value-as-field"), "type": "extra_forbidden", "input": "secret"}]
    )
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "peer,host,allowed",
    [
        ("127.0.0.1", "localhost:8000", True),
        ("::1", "[::1]:8000", True),
        ("testclient", "testserver", True),
        ("198.51.100.2", "localhost:8000", False),
        ("127.0.0.1", "public.example", False),
    ],
)
def test_code_free_initialization_is_limited_to_the_deployment_machine(peer, host, allowed):
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": "/api/v1/auth/setup",
            "headers": [(b"host", host.encode())],
            "client": (peer, 1234),
            "query_string": b"",
        }
    )
    assert local_setup_allowed(request) is allowed
