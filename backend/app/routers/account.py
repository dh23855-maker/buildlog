from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.models.user import User
from app.routers.auth import NICKNAME_TAKEN, nickname_in_use
from app.schemas.auth import NicknameChangeRequest, UserResponse
from app.security import get_current_user

router = APIRouter(prefix="/api/account", tags=["account"])


@router.patch("/nickname", response_model=UserResponse)
def change_nickname(
    body: NicknameChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    # 대상은 항상 로그인한 본인입니다. 다른 사용자의 닉네임은 바꿀 방법이 없습니다.
    if nickname_in_use(db, body.nickname, except_user_id=user.id):
        raise ApiError(409, NICKNAME_TAKEN, "nickname")
    user.nickname = body.nickname
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, NICKNAME_TAKEN, "nickname") from None
    return user
