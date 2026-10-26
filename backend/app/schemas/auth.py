import re

from pydantic import BaseModel, ConfigDict, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NICKNAME_PATTERN = re.compile(r"^[0-9A-Za-z_가-힣]{2,20}$")

PASSWORD_MIN = 8
PASSWORD_MAX = 64


def clean_email(value: str) -> str:
    # 앞뒤 공백을 지우고 소문자로 맞춥니다. 대소문자만 다른 이메일은 같은 이메일입니다.
    value = value.strip().lower()
    if not value:
        raise ValueError("이메일을 입력해 주세요.")
    if len(value) > 254 or not EMAIL_PATTERN.match(value):
        raise ValueError("올바른 이메일 주소를 입력해 주세요.")
    return value


def clean_nickname(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("닉네임을 입력해 주세요.")
    if not NICKNAME_PATTERN.match(value):
        raise ValueError("닉네임은 2~20자의 한글, 영문, 숫자, 밑줄(_)만 사용할 수 있습니다.")
    return value


def check_password(value: str) -> str:
    # 비밀번호는 입력한 그대로 확인합니다. 공백도 지우지 않습니다.
    if not value:
        raise ValueError("비밀번호를 입력해 주세요.")
    if not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN}자 이상 {PASSWORD_MAX}자 이하로 입력해 주세요.")
    return value


class SignupRequest(BaseModel):
    email: str
    password: str
    nickname: str

    _email = field_validator("email")(clean_email)
    _password = field_validator("password")(check_password)
    _nickname = field_validator("nickname")(clean_nickname)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        # 로그인에서는 형식 대신 "맞지 않음"으로만 알려주므로 정리만 합니다.
        return value.strip().lower()


class NicknameChangeRequest(BaseModel):
    nickname: str

    _nickname = field_validator("nickname")(clean_nickname)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str
