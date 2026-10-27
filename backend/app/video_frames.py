"""영상에서 요약할 장면(JPEG)을 뽑습니다. (docs/sdd-ai-summary.md 7장)

- 사용자가 올린 파일을 서버 프로세스 안에서 해석하지 않고 **별도 프로세스(ffmpeg)** 로 실행합니다. 셸을 쓰지 않습니다.
- `-protocol_whitelist file`로 파일 외 입력(네트워크 등)을 막고, `-an -sn`으로 소리·자막은 처리하지 않습니다.
- 장면은 파일이 아니라 표준 출력으로 받으므로 임시 파일이 남지 않습니다.
- ffmpeg는 `imageio-ffmpeg` 패키지에 들어 있는 것을 씁니다. (별도 설치 필요 없음)
"""

import logging
import math
import re
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg

import app.config as config
from app.safe_log import log_exception

logger = logging.getLogger(__name__)

TOTAL_TIMEOUT_SECONDS = 45  # 한 영상에서 장면을 모두 뽑는 데 쓸 수 있는 시간
MAX_FRAME_WIDTH = 768  # 장면의 가로 최대 크기. 이보다 작은 영상은 키우지 않습니다.
FRAMES_PER_SECOND_CAP = 4  # 짧은 영상에서 같은 장면이 중복되지 않도록 초당 최대 장면 수
MAX_FRAME_BYTES = 2 * 1024 * 1024
_JPEG_START = b"\xff\xd8\xff"
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class FrameExtractionError(Exception):
    """장면을 뽑지 못했습니다. 원인 문장은 담지 않습니다. (파일 경로·ffmpeg 출력이 새지 않게)"""


def _ffmpeg() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - 실행 파일을 찾지 못하는 모든 경우
        logger.error("ffmpeg 실행 파일을 찾지 못했습니다")
        raise FrameExtractionError from None


def _run(args: list[str], deadline: float) -> subprocess.CompletedProcess:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FrameExtractionError
    try:
        # 셸 없이, 입력은 막고, 시간이 지나면 프로세스를 종료합니다. (run이 시간 초과 시 자식 프로세스를 종료함)
        return subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=remaining, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg 실행 시간이 초과되었습니다")
        raise FrameExtractionError from None
    except OSError as error:
        log_exception(logger, "ffmpeg를 실행하지 못했습니다", error)
        raise FrameExtractionError from None


def _base_args(exe: str) -> list[str]:
    return [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file"]


def probe_duration(video_path: Path, deadline: float) -> float | None:
    """영상 길이(초)입니다. 읽지 못하면 None."""
    exe = _ffmpeg()
    # 출력 파일 없이 입력만 열면 ffmpeg가 정보를 오류 출력에 적고 오류로 끝납니다. (정상 동작)
    args = [exe, "-nostdin", "-hide_banner", "-protocol_whitelist", "file", "-i", str(video_path)]
    result = _run(args, deadline)
    match = _DURATION.search(result.stderr.decode("utf-8", errors="replace"))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def frame_times(duration: float, max_frames: int) -> list[float]:
    """장면을 뽑을 시각(초)입니다. 영상을 같은 길이로 나눈 구간의 가운데를 시간순으로 돌려줍니다."""
    count = max(1, min(max_frames, int(duration * FRAMES_PER_SECOND_CAP)))
    return [(index + 0.5) * duration / count for index in range(count)]


_SCALE = f"scale=min({MAX_FRAME_WIDTH}\\,iw):-2"


def _frame_at(exe: str, video_path: Path, second: float, deadline: float) -> bytes | None:
    args = _base_args(exe) + [
        "-ss", f"{second:.3f}", "-i", str(video_path),
        "-an", "-sn", "-threads", "1",
        "-frames:v", "1", "-vf", _SCALE, "-q:v", "4", "-f", "mjpeg", "pipe:1",
    ]
    data = _run(args, deadline).stdout
    if data.startswith(_JPEG_START) and 0 < len(data) <= MAX_FRAME_BYTES:
        return data
    return None


def _frames_by_rate(exe: str, video_path: Path, max_frames: int, deadline: float) -> list[bytes]:
    """길이를 알 수 없을 때의 대체 방법: 1초마다 한 장씩 앞에서부터 뽑습니다."""
    args = _base_args(exe) + [
        "-i", str(video_path),
        "-an", "-sn", "-threads", "1",
        "-vf", f"fps=1,{_SCALE}", "-frames:v", str(max_frames), "-q:v", "4", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
    ]
    data = _run(args, deadline).stdout
    parts = [b"\xff\xd8\xff" + chunk for chunk in data.split(_JPEG_START)[1:]]
    return [part for part in parts if 0 < len(part) <= MAX_FRAME_BYTES][:max_frames]


def extract_frames(video_path: Path, max_frames: int = config.AI_MAX_FRAMES) -> list[bytes]:
    """영상에서 시간순으로 최대 `max_frames`장의 JPEG를 뽑습니다. 한 장도 못 뽑으면 FrameExtractionError."""
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    exe = _ffmpeg()
    duration = probe_duration(video_path, deadline)

    if duration and duration > 0 and math.isfinite(duration):
        frames = []
        for second in frame_times(duration, max_frames):
            frame = _frame_at(exe, video_path, second, deadline)
            if frame is not None:  # 끝부분 등 일부 시점에서 못 뽑아도 나머지는 씁니다.
                frames.append(frame)
    else:
        frames = _frames_by_rate(exe, video_path, max_frames, deadline)

    if not frames:
        logger.warning("영상에서 장면을 하나도 뽑지 못했습니다")
        raise FrameExtractionError
    return frames
