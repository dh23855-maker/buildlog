from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.material import Material
from app.models.user import User
from tests.conftest import signup_payload
from tests.test_materials_upload import jpeg, mp4, png, stored_files, upload

NOT_FOUND = {"detail": "자료를 찾을 수 없습니다.", "field": None}
LOGIN_REQUIRED = {"detail": "로그인이 필요합니다.", "field": None}


@pytest.fixture
def two_users(make_client):
    """서로 다른 두 사용자(쿠키)의 클라이언트입니다."""
    clients = []
    for email, nickname in (("a@example.com", "사용자A"), ("b@example.com", "사용자B")):
        c = make_client()
        payload = signup_payload(email=email, nickname=nickname)
        assert c.post("/api/auth/signup", json=payload).status_code == 201
        assert c.post("/api/auth/login", json={"email": email, "password": payload["password"]}).status_code == 200
        clients.append(c)
    return clients


def add_image(client, title="이미지", name="a.png"):
    return upload(client, title=title, files={"file": (name, png(200), "image/png")}).json()


def add_video(client, title="영상", name="a.mp4"):
    return upload(client, title=title, files={"file": (name, mp4(3000), "video/mp4")}).json()


# ---------- 목록 ----------


def test_자료가_없으면_빈_목록과_0개를_돌려준다(logged_in):
    response = logged_in.get("/api/materials")
    assert response.status_code == 200
    assert response.json() == {"items": [], "counts": {"all": 0, "image": 0, "video": 0}, "ai_enabled": False}


def test_목록은_최신_등록순이다(logged_in):
    first = add_image(logged_in, "첫째")
    second = add_video(logged_in, "둘째")
    third = add_image(logged_in, "셋째")

    items = logged_in.get("/api/materials").json()["items"]
    assert [i["id"] for i in items] == [third["id"], second["id"], first["id"]]


def test_등록_시각이_같으면_나중에_등록한_것이_먼저다(logged_in, db):
    user = db.scalar(select(User))
    same = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    ids = []
    for i in range(3):
        m = Material(
            user_id=user.id, title=f"자료{i}", kind="image", original_filename="a.png", content_type="image/png",
            size_bytes=1, storage_name=f"{i:032x}.png", created_at=same,
        )
        db.add(m)
        db.commit()
        ids.append(m.id)

    assert [i["id"] for i in logged_in.get("/api/materials").json()["items"]] == ids[::-1]


def test_시각이_다르면_시각이_우선한다(logged_in, db):
    user = db.scalar(select(User))
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    # id는 나중이지만 등록 시각이 더 오래된 자료
    newer = Material(user_id=user.id, title="최근", kind="image", original_filename="a.png", content_type="image/png",
                     size_bytes=1, storage_name=f"{1:032x}.png", created_at=now)
    older = Material(user_id=user.id, title="오래됨", kind="image", original_filename="b.png", content_type="image/png",
                     size_bytes=1, storage_name=f"{2:032x}.png", created_at=now - timedelta(days=3))
    db.add_all([newer, older])
    db.commit()

    assert [i["title"] for i in logged_in.get("/api/materials").json()["items"]] == ["최근", "오래됨"]


def test_목록에_필요한_정보만_담긴다(logged_in, db):
    add_image(logged_in, "제목", "내사진.png")
    item = logged_in.get("/api/materials").json()["items"][0]
    assert set(item) == {
        "id", "title", "memo", "kind", "original_filename", "content_type", "size_bytes", "created_at",
        "summary", "analysis_status", "analysis_message",
    }
    # 내부 정보는 응답에 없어야 한다
    assert not {'analysis_error', 'analysis_model', 'analyzed_at', 'storage_name', 'user_id'} & set(item)
    assert item["original_filename"] == "내사진.png"
    assert db.scalar(select(Material)).storage_name not in str(item)


def test_필터는_종류별로_걸러내고_개수는_전체_기준이다(logged_in):
    add_image(logged_in, "이미지1")
    add_image(logged_in, "이미지2")
    add_video(logged_in, "영상1")

    everything = logged_in.get("/api/materials").json()
    images = logged_in.get("/api/materials?kind=image").json()
    videos = logged_in.get("/api/materials?kind=video").json()

    assert everything["counts"] == {"all": 3, "image": 2, "video": 1}
    assert [i["title"] for i in images["items"]] == ["이미지2", "이미지1"]
    assert [i["title"] for i in videos["items"]] == ["영상1"]
    assert images["counts"] == videos["counts"] == everything["counts"]  # 필터와 관계없음


def test_알_수_없는_종류로_거르면_거절한다(logged_in):
    response = logged_in.get("/api/materials?kind=audio")
    assert response.status_code == 422
    assert response.json()["field"] == "kind"


def test_목록에는_내_자료만_나온다(two_users):
    a, b = two_users
    add_image(a, "A의 이미지")
    add_video(a, "A의 영상")
    add_image(b, "B의 이미지")

    a_list = a.get("/api/materials").json()
    b_list = b.get("/api/materials").json()
    assert sorted(i["title"] for i in a_list["items"]) == ["A의 영상", "A의 이미지"]
    assert a_list["counts"] == {"all": 2, "image": 1, "video": 1}
    assert [i["title"] for i in b_list["items"]] == ["B의 이미지"]
    assert b_list["counts"] == {"all": 1, "image": 1, "video": 0}


# ---------- 원본 ----------


def test_이미지_원본을_그대로_돌려준다(logged_in):
    content = png(500)
    material = upload(logged_in, files={"file": ("a.png", content, "image/png")}).json()

    response = logged_in.get(f"/api/materials/{material['id']}/file")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize(
    "name, content, content_type",
    [("a.jpg", jpeg(300), "image/jpeg"), ("a.mp4", mp4(300), "video/mp4")],
)
def test_저장된_형식으로_알려준다(logged_in, name, content, content_type):
    material = upload(logged_in, files={"file": (name, content, content_type)}).json()
    response = logged_in.get(f"/api/materials/{material['id']}/file")
    assert response.headers["content-type"] == content_type
    assert response.content == content


def test_영상은_일부분만_요청할_수_있다(logged_in):
    content = mp4(5000)
    material = upload(logged_in, files={"file": ("a.mp4", content, "video/mp4")}).json()
    url = f"/api/materials/{material['id']}/file"

    assert logged_in.get(url).headers["accept-ranges"] == "bytes"
    part = logged_in.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == content[100:200]
    assert part.headers["content-range"] == "bytes 100-199/5000"
    assert part.headers["x-content-type-options"] == "nosniff"
    assert part.headers["cache-control"] == "private, no-store"


def test_다른_사람의_원본은_없는_자료와_똑같이_답한다(two_users):
    a, b = two_users
    material = add_image(a)

    others = b.get(f"/api/materials/{material['id']}/file")
    missing = b.get("/api/materials/999999/file")
    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json() == NOT_FOUND
    assert others.content == missing.content  # 본문까지 같음
    assert a.get(f"/api/materials/{material['id']}/file").status_code == 200


def test_로그인하지_않으면_원본을_볼_수_없다(logged_in, client):
    material = add_image(logged_in)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        response = anonymous.get(f"/api/materials/{material['id']}/file")
    assert response.status_code == 401
    assert response.json() == LOGIN_REQUIRED


def test_파일이_사라졌으면_없는_자료처럼_답하고_경로를_알리지_않는다(logged_in, db, isolated_uploads):
    material = add_image(logged_in)
    for path in isolated_uploads.glob("*"):
        path.unlink()

    response = logged_in.get(f"/api/materials/{material['id']}/file")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert "uploads" not in response.text


def test_올바르지_않은_자료_번호는_거절한다(logged_in):
    assert logged_in.get("/api/materials/abc/file").status_code == 422
    assert logged_in.delete("/api/materials/abc").status_code == 422


def test_저장_이름이_이상한_자료는_폴더_밖_파일을_주지_않는다(logged_in, db, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(png(100))
    user = db.scalar(select(User))
    row = Material(user_id=user.id, title="조작됨", kind="image", original_filename="a.png", content_type="image/png",
                   size_bytes=100, storage_name="../../secret.png")
    db.add(row)
    db.commit()

    response = logged_in.get(f"/api/materials/{row.id}/file")
    assert response.status_code == 404
    assert response.content != outside.read_bytes()


# ---------- 삭제 ----------


def test_삭제하면_자료_정보와_파일이_함께_사라진다(logged_in, db, isolated_uploads):
    material = add_image(logged_in)
    assert len(stored_files(isolated_uploads)) == 1

    response = logged_in.delete(f"/api/materials/{material['id']}")
    assert response.status_code == 204
    assert response.content == b""
    db.expire_all()
    assert db.scalars(select(Material)).all() == []
    assert stored_files(isolated_uploads) == []
    assert logged_in.get("/api/materials").json()["items"] == []


def test_삭제한_뒤에는_목록_개수와_원본_주소에_반영된다(logged_in):
    keep = add_image(logged_in, "남길 것")
    gone = add_video(logged_in, "지울 것")

    assert logged_in.delete(f"/api/materials/{gone['id']}").status_code == 204

    listing = logged_in.get("/api/materials").json()
    assert [i["id"] for i in listing["items"]] == [keep["id"]]
    assert listing["counts"] == {"all": 1, "image": 1, "video": 0}
    assert logged_in.get(f"/api/materials/{gone['id']}/file").status_code == 404
    assert logged_in.get(f"/api/materials/{keep['id']}/file").status_code == 200


def test_이미_지운_자료를_다시_지우면_없다고_답한다(logged_in):
    material = add_image(logged_in)
    assert logged_in.delete(f"/api/materials/{material['id']}").status_code == 204
    again = logged_in.delete(f"/api/materials/{material['id']}")
    assert again.status_code == 404
    assert again.json() == NOT_FOUND


def test_다른_사람의_자료는_지울_수_없고_원래_자료가_그대로_남는다(two_users, db, isolated_uploads):
    a, b = two_users
    material = add_image(a)

    others = b.delete(f"/api/materials/{material['id']}")
    missing = b.delete("/api/materials/999999")
    assert others.status_code == missing.status_code == 404
    assert others.json() == missing.json() == NOT_FOUND
    assert others.content == missing.content

    db.expire_all()
    assert len(db.scalars(select(Material)).all()) == 1
    assert len(stored_files(isolated_uploads)) == 1
    assert a.get(f"/api/materials/{material['id']}/file").status_code == 200


def test_로그인하지_않으면_지울_수_없다(logged_in, db, isolated_uploads):
    material = add_image(logged_in)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:
        response = anonymous.delete(f"/api/materials/{material['id']}")
    assert response.status_code == 401
    db.expire_all()
    assert len(db.scalars(select(Material)).all()) == 1
    assert len(stored_files(isolated_uploads)) == 1


def test_파일이_이미_없어도_삭제는_성공한다(logged_in, db, isolated_uploads):
    material = add_image(logged_in)
    for path in isolated_uploads.glob("*"):
        path.unlink()

    assert logged_in.delete(f"/api/materials/{material['id']}").status_code == 204
    db.expire_all()
    assert db.scalars(select(Material)).all() == []


def test_파일을_지우지_못해도_사용자에게는_삭제된_것으로_보인다(logged_in, db, monkeypatch, caplog):
    material = add_image(logged_in)

    def boom(self, missing_ok=False):
        raise OSError("권한 없음")

    with monkeypatch.context() as patch:  # (undo()는 임시 업로드 폴더 설정까지 되돌리므로 쓰지 않습니다)
        patch.setattr(Path, "unlink", boom)
        response = logged_in.delete(f"/api/materials/{material['id']}")

    assert response.status_code == 204
    db.expire_all()
    assert db.scalars(select(Material)).all() == []
    assert "파일을 지우지 못했습니다" in caplog.text  # 나중에 정리할 수 있게 기록


def test_데이터베이스에서_지우지_못하면_자료와_파일이_그대로_남는다(logged_in, db, isolated_uploads, monkeypatch):
    material = add_image(logged_in)

    def boom(self):
        raise OperationalError("COMMIT", {}, Exception("연결 끊김"))

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", boom)
        response = logged_in.delete(f"/api/materials/{material['id']}")

    assert response.status_code == 500
    assert response.json()["detail"] == "자료를 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요."
    db.expire_all()
    assert len(db.scalars(select(Material)).all()) == 1
    assert len(stored_files(isolated_uploads)) == 1
    assert logged_in.get(f"/api/materials/{material['id']}/file").status_code == 200


def test_저장_이름이_이상한_자료를_지워도_폴더_밖_파일은_지워지지_않는다(logged_in, db, tmp_path):
    outside = tmp_path / "keep.png"
    outside.write_bytes(png(100))
    user = db.scalar(select(User))
    row = Material(user_id=user.id, title="조작됨", kind="image", original_filename="a.png", content_type="image/png",
                   size_bytes=100, storage_name="../../keep.png")
    db.add(row)
    db.commit()

    assert logged_in.delete(f"/api/materials/{row.id}").status_code == 204
    assert outside.exists()


# ---------- 로그아웃 후 ----------


def test_로그아웃하면_세_주소_모두_로그인이_필요하다(logged_in):
    material = add_image(logged_in)
    assert logged_in.post("/api/auth/logout").status_code == 204

    for response in (
        logged_in.get("/api/materials"),
        logged_in.get(f"/api/materials/{material['id']}/file"),
        logged_in.delete(f"/api/materials/{material['id']}"),
    ):
        assert response.status_code == 401
        assert response.json() == LOGIN_REQUIRED
