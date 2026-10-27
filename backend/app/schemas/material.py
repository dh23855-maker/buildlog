from datetime import datetime

from pydantic import BaseModel, ConfigDict

TITLE_MAX = 100
MEMO_MAX = 1000


def clean_title(value: str) -> str:
    # 앞뒤 공백을 지운 뒤 길이를 봅니다. 공백만 있으면 비어 있는 것으로 봅니다.
    value = value.strip()
    if not value:
        raise ValueError("제목을 입력해 주세요.")
    if len(value) > TITLE_MAX:
        raise ValueError(f"제목은 {TITLE_MAX}자 이하로 입력해 주세요.")
    _reject_null(value)
    return value


def clean_memo(value: str) -> str | None:
    # 메모는 선택 입력입니다. 비어 있으면 저장하지 않고(NULL) 비웁니다.
    value = value.strip()
    if not value:
        return None
    if len(value) > MEMO_MAX:
        raise ValueError(f"메모는 {MEMO_MAX:,}자 이하로 입력해 주세요.")
    _reject_null(value)
    return value


def _reject_null(value: str) -> None:
    # NUL 문자는 PostgreSQL이 문자열로 저장하지 못해 오류가 나므로 미리 막습니다.
    if "\x00" in value:
        raise ValueError("사용할 수 없는 문자가 들어 있어요.")


class MaterialResponse(BaseModel):
    """화면에 보내는 자료 정보입니다. 서버 내부 정보(저장 파일 이름, 경로, 사용자 번호)는 넣지 않습니다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    memo: str | None
    kind: str
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    # AI 요약. 내부 정보(실패 코드, 모델 이름, 분석 시각)는 보내지 않습니다.
    summary: str | None = None
    analysis_status: str = "skipped"
    # failed일 때 사용자에게 보여줄 문장. 코드를 문장으로 바꾸는 일은 Phase A3에서 연결합니다.
    analysis_message: str | None = None


class MaterialCounts(BaseModel):
    """필터와 관계없는 종류별 개수입니다."""

    all: int
    image: int
    video: int


class MaterialListResponse(BaseModel):
    items: list[MaterialResponse]
    counts: MaterialCounts
    # 서버에 OpenAI 키가 있어 AI 요약을 쓸 수 있는지. 화면이 체크박스·버튼을 보여줄지 정하는 데 씁니다.
    ai_enabled: bool = False
