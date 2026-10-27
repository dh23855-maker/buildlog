import os
import struct
import subprocess

import imageio_ffmpeg
import pytest

import app.config as config
from app import video_frames
from app.video_frames import FrameExtractionError, extract_frames, frame_times


def make_video(path, *, seconds=4.0, size="320x240", rate=10):
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", f"testsrc=duration={seconds}:size={size}:rate={rate}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    return path


def jpeg_size(data: bytes) -> tuple[int, int]:
    """JPEG 머리 부분에서 (가로, 세로)를 읽습니다. 이미지 라이브러리 없이 확인하기 위한 것입니다."""
    position = 2
    while position < len(data):
        marker = data[position + 1]
        length = struct.unpack(">H", data[position + 2 : position + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[position + 5 : position + 9])
            return width, height
        position += 2 + length
    raise AssertionError("JPEG 크기를 찾지 못했습니다")


@pytest.fixture
def video(tmp_path):
    return make_video(tmp_path / "sample.mp4")


# ---------- 장면 시각 ----------


def test_장면은_구간의_가운데_시각이고_시간순이다():
    assert frame_times(4.0, 8) == [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75]
    assert frame_times(4.0, 4) == [0.5, 1.5, 2.5, 3.5]


@pytest.mark.parametrize("duration, expected_count", [(0.1, 1), (0.3, 1), (0.5, 2), (1.0, 4), (2.0, 8), (60.0, 8), (3600.0, 8)])
def test_짧은_영상은_같은_장면이_중복되지_않게_초당_4장까지만_뽑는다(duration, expected_count):
    times = frame_times(duration, 8)
    assert len(times) == expected_count
    assert times == sorted(times)
    assert all(0 < t < duration for t in times)


# ---------- 추출 ----------


def test_영상에서_최대_8장을_시간순_JPEG로_뽑는다(video):
    frames = extract_frames(video)
    assert len(frames) == 8
    for frame in frames:
        assert frame.startswith(b"\xff\xd8\xff") and frame.endswith(b"\xff\xd9")
    assert len(set(frames)) == 8  # 시간에 따라 화면이 바뀌므로 모두 다른 장면


def test_장면_수를_지정할_수_있다(video):
    assert len(extract_frames(video, max_frames=3)) == 3
    assert len(extract_frames(video, max_frames=1)) == 1


def test_가로가_768을_넘는_영상은_768로_줄이고_작은_영상은_키우지_않는다(tmp_path):
    big = make_video(tmp_path / "big.mp4", seconds=1, size="1280x720")
    small = make_video(tmp_path / "small.mp4", seconds=1, size="320x240")
    assert {jpeg_size(f) for f in extract_frames(big)} == {(768, 432)}
    assert {jpeg_size(f) for f in extract_frames(small)} == {(320, 240)}


def test_아주_짧은_영상도_한_장은_뽑는다(tmp_path):
    short = make_video(tmp_path / "short.mp4", seconds=0.2)
    frames = extract_frames(short)
    assert 1 <= len(frames) <= 2


def test_길이를_모르면_1초마다_앞에서부터_뽑는다(video, monkeypatch):
    monkeypatch.setattr(video_frames, "probe_duration", lambda path, deadline: None)
    frames = extract_frames(video)
    assert 1 <= len(frames) <= 8
    assert all(f.startswith(b"\xff\xd8\xff") for f in frames)
    assert len(set(frames)) == len(frames)


def test_길이를_읽을_수_있다(video):
    import time

    assert video_frames.probe_duration(video, time.monotonic() + 30) == pytest.approx(4.0, abs=0.1)


def test_영상_옆에_파일을_남기지_않는다(video, tmp_path):
    before = sorted(os.listdir(tmp_path))
    extract_frames(video)
    assert sorted(os.listdir(tmp_path)) == before


# ---------- 실패 ----------


@pytest.mark.parametrize(
    "content",
    [b"", b"\x00" * 100, ("이것은 영상이 아닙니다" * 20).encode(), b"\x89PNG\r\n\x1a\n" + b"\x00" * 100],
    ids=["빈 파일", "0으로 채운 파일", "글자 파일", "PNG 이미지"],
)
def test_영상이_아닌_파일은_오류다(tmp_path, content):
    path = tmp_path / "fake.mp4"
    path.write_bytes(content)
    with pytest.raises(FrameExtractionError):
        extract_frames(path)


def test_없는_파일은_오류다(tmp_path):
    with pytest.raises(FrameExtractionError):
        extract_frames(tmp_path / "none.mp4")


def test_중간에_잘린_영상은_뽑을_수_있는_만큼만_뽑거나_오류다(video, tmp_path):
    data = video.read_bytes()
    broken = tmp_path / "cut.mp4"
    broken.write_bytes(data[: len(data) // 2])
    try:
        frames = extract_frames(broken)
    except FrameExtractionError:
        return  # 오류로 끝나도 괜찮다 (다른 종류의 예외만 아니면 됨)
    assert frames and all(f.startswith(b"\xff\xd8\xff") for f in frames)


def test_ffmpeg_실행_시간이_초과되면_오류다(video, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(video_frames.subprocess, "run", slow)
    with pytest.raises(FrameExtractionError):
        extract_frames(video)


def test_전체_제한_시간이_지나면_더_실행하지_않는다(video, monkeypatch):
    calls = []
    real_run = subprocess.run
    monkeypatch.setattr(video_frames, "TOTAL_TIMEOUT_SECONDS", -1)
    monkeypatch.setattr(video_frames.subprocess, "run", lambda *a, **k: calls.append(1) or real_run(*a, **k))
    with pytest.raises(FrameExtractionError):
        extract_frames(video)
    assert calls == []


def test_ffmpeg를_찾지_못하면_오류다(video, monkeypatch):
    def missing():
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(video_frames.imageio_ffmpeg, "get_ffmpeg_exe", missing)
    with pytest.raises(FrameExtractionError):
        extract_frames(video)


def test_ffmpeg를_실행하지_못하면_오류다(video, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("실행 불가")

    monkeypatch.setattr(video_frames.subprocess, "run", boom)
    with pytest.raises(FrameExtractionError):
        extract_frames(video)


def test_오류에_경로나_ffmpeg_출력이_담기지_않는다(tmp_path):
    path = tmp_path / "비밀폴더" / "fake.mp4"
    path.parent.mkdir()
    path.write_bytes(b"not video")
    with pytest.raises(FrameExtractionError) as raised:
        extract_frames(path)
    assert "비밀폴더" not in str(raised.value) and not raised.value.args


# ---------- 안전 ----------


def test_ffmpeg는_셸_없이_제한된_옵션으로_실행된다(video, monkeypatch):
    seen = []
    real_run = subprocess.run

    def spy(args, **kwargs):
        seen.append((list(args), kwargs))
        return real_run(args, **kwargs)

    monkeypatch.setattr(video_frames.subprocess, "run", spy)
    extract_frames(video, max_frames=2)

    assert seen
    for args, kwargs in seen:
        assert isinstance(args, list)  # 문자열 명령(셸)이 아님
        assert not kwargs.get("shell")
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] <= video_frames.TOTAL_TIMEOUT_SECONDS
        assert "-nostdin" in args
        assert args[args.index("-protocol_whitelist") + 1] == "file"  # 파일 외 입력(네트워크 등) 차단
    frame_calls = [a for a, _ in seen if "-frames:v" in a]
    assert frame_calls
    for args in frame_calls:
        assert "-an" in args and "-sn" in args  # 소리·자막은 처리하지 않음
        assert args[args.index("-threads") + 1] == "1"


def test_다른_파일을_읽게_만드는_목록_파일은_받아들이지_않는다(tmp_path):
    secret = tmp_path / "secret.mp4"
    make_video(secret, seconds=1)
    # concat 목록으로 위장한 파일: 다른 영상 파일을 끌어와 읽게 만들려는 시도
    trick = tmp_path / "trick.mp4"
    trick.write_text(f"ffconcat version 1.0\nfile '{secret.as_posix()}'\n", encoding="utf-8")
    with pytest.raises(FrameExtractionError):
        extract_frames(trick)


def _listening_socket():
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.5)
    return server


def _connections(server) -> int:
    count = 0
    while True:
        try:
            connection, _ = server.accept()
        except OSError:  # 시간 초과: 더 이상 연결이 없음
            return count
        connection.close()
        count += 1


def test_외부_주소를_불러오게_만드는_재생목록은_연결을_시도하지_않는다(tmp_path):
    # 재생목록에 적힌 http 주소로 연결하지 않아야 한다. (ffmpeg 기본 설정과 우리의 `-protocol_whitelist file`이 함께 막는다.
    # 우리 옵션이 빠지지 않았는지는 '셸 없이 제한된 옵션으로 실행된다' 테스트가 따로 확인한다.)
    server = _listening_socket()
    try:
        port = server.getsockname()[1]
        playlist = tmp_path / "list.m3u8"
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXTINF:1.0,", f"http://127.0.0.1:{port}/never.ts", "#EXT-X-ENDLIST", ""]
        playlist.write_text("\n".join(lines), encoding="utf-8")

        with pytest.raises(FrameExtractionError):
            extract_frames(playlist)
        assert _connections(server) == 0
    finally:
        server.close()


def test_최대_장면_수와_제한은_설정을_따른다():
    assert config.AI_MAX_FRAMES == 8
    assert video_frames.MAX_FRAME_WIDTH == 768
    assert video_frames.TOTAL_TIMEOUT_SECONDS == 45
