import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.storage as storage
from app.models.material import Material

MB = 1024 * 1024
PNG_HEAD = b"\x89PNG\r\n\x1a\n"
JPEG_HEAD = b"\xff\xd8\xff\xe0"
MP4_HEAD = b"\x00\x00\x00\x18ftypmp42"
MOV_HEAD = b"\x00\x00\x00\x14ftypqt  "


def png(size=100):
    return PNG_HEAD + b"\x00" * (size - len(PNG_HEAD))


def jpeg(size=100):
    return JPEG_HEAD + b"\x00" * (size - len(JPEG_HEAD))


def mp4(size=100):
    return MP4_HEAD + b"\x00" * (size - len(MP4_HEAD))


def upload(client, *, title="REST API 정리", memo=None, files=None, **extra):
    data = {"title": title}
    if memo is not None:
        data["memo"] = memo
    data.update(extra)
    if files is None:
        files = {"file": ("rest.png", png(), "image/png")}
    return client.post("/api/materials", data=data, files=files)


def stored_files(uploads_dir):
    return sorted(p.name for p in uploads_dir.glob("*")) if uploads_dir.exists() else []


def assert_nothing_stored(db, uploads_dir):
    db.expire_all()
    assert db.scalars(select(Material)).all() == []
    assert stored_files(uploads_dir) == []


# ---------- 정상 ----------


@pytest.mark.parametrize(
    "name, content, content_type, kind, size, saved_ext",
    [
        ("shot.png", png(1234), "image/png", "image", 1234, ".png"),
        ("photo.jpg", jpeg(2048), "image/jpeg", "image", 2048, ".jpg"),
        ("photo.JPEG", jpeg(10), "image/jpeg", "image", 10, ".jpg"),
        ("demo.mp4", mp4(4096), "video/mp4", "video", 4096, ".mp4"),
    ],
)
def test_PNG_JPG_MP4를_올리면_저장된다(logged_in, db, isolated_uploads, name, content, content_type, kind, size, saved_ext):
    response = upload(logged_in, memo="메모", files={"file": (name, content, content_type)})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "REST API 정리"
    assert body["memo"] == "메모"
    assert body["kind"] == kind
    assert body["content_type"] == content_type
    assert body["size_bytes"] == size
    assert body["original_filename"] == name
    assert body["created_at"]

    row = db.scalar(select(Material))
    assert row.id == body["id"]
    saved = isolated_uploads / row.storage_name
    assert row.storage_name.endswith(saved_ext)
    assert saved.read_bytes() == content
    assert stored_files(isolated_uploads) == [row.storage_name]  # 임시 파일이 남지 않음


def test_자료는_로그인한_사용자의_것이_된다(logged_in, db):
    upload(logged_in)
    from app.models.user import User

    assert db.scalar(select(Material)).user_id == db.scalar(select(User)).id


def test_응답에_서버_내부_정보가_없다(logged_in, db):
    body = upload(logged_in).json()
    row = db.scalar(select(Material))
    assert set(body) == {
        "id", "title", "memo", "kind", "original_filename", "content_type", "size_bytes", "created_at",
        "summary", "analysis_status", "analysis_message",
    }
    # 내부 정보는 응답에 없어야 한다
    assert not {'analysis_error', 'analysis_model', 'analyzed_at', 'storage_name', 'user_id'} & set(body)
    assert row.storage_name not in str(body)
    assert "uploads" not in str(body)


def test_제목_앞뒤_공백은_지우고_메모가_비어_있으면_비운다(logged_in, db):
    upload(logged_in, title="  제목  ", memo="   ")
    row = db.scalar(select(Material))
    assert row.title == "제목"
    assert row.memo is None


def test_메모를_보내지_않아도_된다(logged_in):
    assert upload(logged_in).json()["memo"] is None


def test_제목_100자와_메모_1000자는_통과한다(logged_in):
    assert upload(logged_in, title="가" * 100, memo="나" * 1000).status_code == 201


# ---------- 경계 크기 ----------


def test_정확히_5MB_PNG는_통과하고_1바이트_넘으면_거절한다(logged_in, db, isolated_uploads):
    assert upload(logged_in, files={"file": ("a.png", png(5 * MB), "image/png")}).status_code == 201
    assert db.scalar(select(Material)).size_bytes == 5 * MB

    over = upload(logged_in, files={"file": ("b.png", png(5 * MB + 1), "image/png")})
    assert over.status_code == 413
    assert over.json()["field"] == "file"
    assert "5MB" in over.json()["detail"]
    assert len(stored_files(isolated_uploads)) == 1  # 첫 번째 파일만 남음


def test_5MB를_넘는_JPG는_거절한다(logged_in, db, isolated_uploads):
    response = upload(logged_in, files={"file": ("a.jpg", jpeg(5 * MB + 1), "image/jpeg")})
    assert response.status_code == 413
    assert_nothing_stored(db, isolated_uploads)


def test_정확히_30MB_MP4는_통과하고_1바이트_넘으면_거절한다(logged_in, db, isolated_uploads):
    assert upload(logged_in, files={"file": ("a.mp4", mp4(30 * MB), "video/mp4")}).status_code == 201

    over = upload(logged_in, files={"file": ("b.mp4", mp4(30 * MB + 1), "video/mp4")})
    assert over.status_code == 413
    assert "30MB" in over.json()["detail"]
    assert len(stored_files(isolated_uploads)) == 1


def test_이미지_한도를_영상에는_적용하지_않는다(logged_in):
    # 6MB MP4는 통과해야 합니다. (이미지 한도 5MB를 넘지만 영상 한도 30MB 이내)
    assert upload(logged_in, files={"file": ("a.mp4", mp4(6 * MB), "video/mp4")}).status_code == 201


def test_요청_전체가_너무_크면_받기_전에_거절한다(logged_in, db, isolated_uploads):
    response = upload(logged_in, files={"file": ("a.mp4", mp4(33 * MB), "video/mp4")})
    assert response.status_code == 413
    assert response.json()["field"] == "file"
    assert_nothing_stored(db, isolated_uploads)


# ---------- 입력 검사 ----------


@pytest.mark.parametrize(
    "title, message",
    [("", "제목을 입력해 주세요."), ("   ", "제목을 입력해 주세요."), ("가" * 101, "제목은 100자 이하로 입력해 주세요.")],
)
def test_제목이_잘못되면_거절한다(logged_in, db, isolated_uploads, title, message):
    response = upload(logged_in, title=title)
    assert response.status_code == 422
    assert response.json() == {"detail": message, "field": "title"}
    assert_nothing_stored(db, isolated_uploads)


def test_제목을_보내지_않아도_거절한다(logged_in, db, isolated_uploads):
    response = logged_in.post("/api/materials", files={"file": ("a.png", png(), "image/png")})
    assert response.status_code == 422
    assert response.json()["field"] == "title"
    assert_nothing_stored(db, isolated_uploads)


def test_메모가_1000자를_넘으면_거절한다(logged_in, db, isolated_uploads):
    response = upload(logged_in, memo="나" * 1001)
    assert response.status_code == 422
    assert response.json() == {"detail": "메모는 1,000자 이하로 입력해 주세요.", "field": "memo"}
    assert_nothing_stored(db, isolated_uploads)


def test_NUL_문자가_들어간_제목과_메모는_거절한다(logged_in, db, isolated_uploads):
    assert upload(logged_in, title="제목\x00").json()["field"] == "title"
    assert upload(logged_in, memo="메모\x00").json()["field"] == "memo"
    assert_nothing_stored(db, isolated_uploads)


def test_파일이_없으면_거절한다(logged_in, db, isolated_uploads):
    response = logged_in.post("/api/materials", data={"title": "제목"})
    assert response.status_code == 422
    assert response.json() == {"detail": "파일을 선택해 주세요.", "field": "file"}
    assert_nothing_stored(db, isolated_uploads)


def test_파일이_두_개_이상이면_거절한다(logged_in, db, isolated_uploads):
    files = [("file", ("a.png", png(), "image/png")), ("file", ("b.png", png(), "image/png"))]
    response = upload(logged_in, files=files)
    assert response.status_code == 422
    assert response.json()["field"] == "file"
    assert_nothing_stored(db, isolated_uploads)


def test_빈_파일은_거절한다(logged_in, db, isolated_uploads):
    response = upload(logged_in, files={"file": ("empty.png", b"", "image/png")})
    assert response.status_code == 422
    assert response.json() == {"detail": "비어 있는 파일은 올릴 수 없어요.", "field": "file"}
    assert_nothing_stored(db, isolated_uploads)


@pytest.mark.parametrize(
    "name, content, content_type",
    [
        ("anim.gif", b"GIF89a" + b"\x00" * 50, "image/gif"),
        ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ("pic.webp", b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
        ("clip.mov", MOV_HEAD + b"\x00" * 50, "video/quicktime"),
        ("noext", png(), "image/png"),
        ("script.png.exe", png(), "application/octet-stream"),
        # 확장자만 바꾼 가짜 파일
        ("fake.png", b"hello text file", "image/png"),
        ("fake.jpg", png(), "image/jpeg"),
        ("fake.png", jpeg(), "image/png"),
        ("fake.mp4", png(), "video/mp4"),
        ("fake.png", mp4(), "image/png"),
        # MOV를 .mp4로 바꾼 파일
        ("fake.mp4", MOV_HEAD + b"\x00" * 50, "video/mp4"),
        # 너무 짧아 표식을 확인할 수 없는 파일
        ("tiny.mp4", b"\x00\x00", "video/mp4"),
        # 브라우저가 알린 형식이 확장자와 다름
        ("a.png", png(), "image/jpeg"),
        ("a.mp4", mp4(), "image/png"),
        ("a.png", png(), "application/octet-stream"),
    ],
)
def test_허용하지_않는_파일은_거절한다(logged_in, db, isolated_uploads, name, content, content_type):
    response = upload(logged_in, files={"file": (name, content, content_type)})
    assert response.status_code == 415
    assert response.json() == {"detail": "PNG, JPG, MP4 파일만 올릴 수 있어요.", "field": "file"}
    assert_nothing_stored(db, isolated_uploads)


# ---------- 안전 ----------


@pytest.mark.parametrize("name", ["../../evil.png", "..\\..\\evil.png", "/etc/evil.png", "C:\\Windows\\evil.png"])
def test_파일_이름으로_폴더_밖에_쓸_수_없다(logged_in, db, isolated_uploads, tmp_path, name):
    response = upload(logged_in, files={"file": (name, png(), "image/png")})

    assert response.status_code == 201
    assert response.json()["original_filename"] == "evil.png"
    row = db.scalar(select(Material))
    assert "evil" not in row.storage_name  # 저장 이름에 사용자가 정한 이름이 쓰이지 않음
    assert stored_files(isolated_uploads) == [row.storage_name]
    assert list(tmp_path.rglob("evil*")) == []
    assert [p.name for p in isolated_uploads.parent.iterdir()] == ["materials"]


def test_긴_파일_이름은_255자로_자른다(logged_in):
    response = upload(logged_in, files={"file": ("가" * 300 + ".png", png(), "image/png")})
    assert response.status_code == 201
    assert len(response.json()["original_filename"]) == 255


def test_같은_파일을_두_번_올려도_저장_이름은_겹치지_않는다(logged_in, db, isolated_uploads):
    upload(logged_in)
    upload(logged_in)
    names = [m.storage_name for m in db.scalars(select(Material))]
    assert len(set(names)) == 2
    assert stored_files(isolated_uploads) == sorted(names)


# ---------- 로그인 ----------


def test_로그인하지_않으면_거절하고_파일을_저장하지_않는다(client, db, isolated_uploads):
    response = upload(client)
    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다.", "field": None}
    assert_nothing_stored(db, isolated_uploads)


def test_로그아웃한_뒤에는_올릴_수_없다(logged_in, db, isolated_uploads):
    assert logged_in.post("/api/auth/logout").status_code in (200, 204)
    assert upload(logged_in).status_code == 401
    assert_nothing_stored(db, isolated_uploads)


def test_사용자마다_자기_자료가_된다(make_client, db):
    from tests.conftest import signup_payload

    owners = {}
    for email, nickname in (("a@example.com", "사용자A"), ("b@example.com", "사용자B")):
        c = make_client()
        payload = signup_payload(email=email, nickname=nickname)
        assert c.post("/api/auth/signup", json=payload).status_code == 201
        assert c.post("/api/auth/login", json={"email": email, "password": payload["password"]}).status_code == 200
        owners[nickname] = upload(c, title=f"{nickname}의 자료").json()["id"]

    from app.models.user import User

    rows = {m.id: m.user_id for m in db.scalars(select(Material))}
    users = {u.nickname: u.id for u in db.scalars(select(User))}
    assert rows[owners["사용자A"]] == users["사용자A"]
    assert rows[owners["사용자B"]] == users["사용자B"]
    assert users["사용자A"] != users["사용자B"]


# ---------- 실패하면 아무것도 남기지 않음 ----------


def test_데이터베이스_확정에_실패하면_파일도_자료도_남지_않는다(logged_in, db, isolated_uploads, monkeypatch):
    def boom(self):
        raise OperationalError("COMMIT", {}, Exception("연결 끊김"))

    monkeypatch.setattr(Session, "commit", boom)
    response = upload(logged_in)
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["detail"] == "자료를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
    assert response.json()["field"] is None
    assert_nothing_stored(db, isolated_uploads)


def test_데이터베이스_저장에_실패하면_임시_파일도_남지_않는다(logged_in, db, isolated_uploads, monkeypatch):
    def boom(self, *args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("저장 실패"))

    monkeypatch.setattr(Session, "flush", boom)
    response = upload(logged_in)
    monkeypatch.undo()

    assert response.status_code == 500
    assert_nothing_stored(db, isolated_uploads)


def test_파일_이름을_바꾸지_못하면_자료도_파일도_남지_않는다(logged_in, db, isolated_uploads, monkeypatch):
    def boom(src, dst):
        raise OSError("디스크 오류")

    monkeypatch.setattr(storage.os, "replace", boom)
    response = upload(logged_in)
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["detail"] == "파일을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
    assert_nothing_stored(db, isolated_uploads)


def test_폴더를_만들지_못하면_자료가_남지_않는다(logged_in, db, isolated_uploads, monkeypatch):
    from pathlib import Path

    def boom(self, *args, **kwargs):
        raise OSError("권한 없음")

    monkeypatch.setattr(Path, "mkdir", boom)
    response = upload(logged_in)
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["detail"] == "파일을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
    assert_nothing_stored(db, isolated_uploads)


def test_실패한_뒤에도_다시_올릴_수_있다(logged_in, db, isolated_uploads):
    assert upload(logged_in, files={"file": ("a.gif", b"GIF89a", "image/gif")}).status_code == 415
    assert upload(logged_in).status_code == 201
    assert len(db.scalars(select(Material)).all()) == 1
    assert len(stored_files(isolated_uploads)) == 1


def test_테스트는_실제_backend_uploads_폴더를_건드리지_않는다(logged_in):
    from pathlib import Path

    real = Path(__file__).resolve().parent.parent / "uploads"

    def snapshot():
        # 폴더가 없을 수도 있고(서버를 한 번도 쓰지 않음), 이미 있을 수도 있습니다. 내용이 달라지지 않으면 됩니다.
        return sorted(str(p.relative_to(real)) for p in real.rglob("*")) if real.exists() else None

    before = snapshot()
    assert upload(logged_in).status_code == 201
    assert snapshot() == before
