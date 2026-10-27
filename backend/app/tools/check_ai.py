r"""AI 요약 연결 확인 명령입니다.

    backend 폴더에서:  .\.venv\Scripts\python -m app.tools.check_ai
    영상까지 확인:     .\.venv\Scripts\python -m app.tools.check_ai --video

작은 테스트 이미지를 직접 만들어 실제 OpenAI로 요약해 보고, 모델 이름·걸린 시간·토큰 사용량·요약문을 보여줍니다.
키 값은 어디에도 출력하지 않습니다. 문제가 있으면 무엇을 확인해야 하는지 알려줍니다. (요청 1번, 비용은 1원 안팎)
"""

import argparse
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import imageio_ffmpeg

import app.config as config
from app import openai_client, video_frames

# 5x7 글자 모양 (BUILDLOG). 외부 이미지 라이브러리 없이 테스트 이미지를 만들기 위한 것입니다.
_GLYPHS = {
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
}
_TEXT = "BUILDLOG"
_SCALE = 12


def make_sample_png() -> bytes:
    """흰 바탕에 'BUILDLOG' 글자와 파란 밑줄이 있는 PNG를 만듭니다."""
    margin = 30
    glyph_w, glyph_h = 5, 7
    width = margin * 2 + len(_TEXT) * (glyph_w + 1) * _SCALE
    height = margin * 2 + glyph_h * _SCALE + 30
    white, dark, blue = (255, 255, 255), (25, 31, 40), (49, 130, 246)
    pixels = [[white] * width for _ in range(height)]
    for index, char in enumerate(_TEXT):
        left = margin + index * (glyph_w + 1) * _SCALE
        for row, bits in enumerate(_GLYPHS[char]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(_SCALE):
                        for dx in range(_SCALE):
                            pixels[margin + row * _SCALE + dy][left + col * _SCALE + dx] = dark
    bar_top = margin + glyph_h * _SCALE + 14
    for y in range(bar_top, bar_top + 8):
        for x in range(margin, width - margin):
            pixels[y][x] = blue

    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in pixels)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def make_sample_video(path: Path) -> None:
    """번들된 ffmpeg로 6초짜리 테스트 영상(시험용 화면과 숫자 시계)을 만듭니다."""
    args = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc=duration=6:size=640x360:rate=10", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
    ]
    subprocess.run(args, check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)


# 오류 코드별로 "무엇을 확인할지" 알려줍니다.
_HINTS = {
    "auth": "키가 올바른지 확인하세요. backend/.env의 OPENAI_API_KEY 값이 잘렸거나 따옴표·공백이 섞이지 않았는지, 키가 폐기되지 않았는지 확인합니다.",
    "billing": "OpenAI 계정의 결제·사용 한도(Billing)를 확인하세요. 크레딧이 없거나 월 한도를 넘었을 수 있습니다.",
    "rate_limit": "잠시 후 다시 실행해 보세요. 계속되면 OpenAI 계정의 요청 한도(Rate limits)를 확인합니다.",
    "timeout": "인터넷 연결(방화벽·프록시 포함)을 확인하세요.",
    "model": "OPENAI_MODEL 값이 올바른지, 이 키로 그 모델을 쓸 수 있는지 확인하세요. 비워 두면 기본 모델을 씁니다.",
    "server": "OpenAI 쪽의 일시적인 문제일 수 있습니다. 잠시 후 다시 실행해 보세요.",
    "refused": "테스트 이미지를 처리하지 못했습니다. 모델 설정을 확인하세요.",
    "empty": "모델이 빈 응답을 돌려줬습니다. 다른 모델(OPENAI_MODEL)로 시도해 보세요.",
}


def main(argv: list[str] | None = None, client=None) -> int:
    parser = argparse.ArgumentParser(description="AI 요약 연결 확인")
    parser.add_argument("--video", action="store_true", help="테스트 영상을 만들어 장면 추출과 영상 요약까지 확인")
    options = parser.parse_args(argv)

    print("== AI 요약 연결 확인 ==")
    settings = config.settings
    if not settings.ai_enabled:
        print("결과: 실패 - OPENAI_API_KEY가 설정되어 있지 않습니다.")
        print("확인할 것:")
        print("  1. backend 폴더에 .env 파일이 있는지 (backend/.env.example을 복사해서 만듭니다)")
        print("  2. .env 안에 OPENAI_API_KEY=키값 줄이 있고, 앞에 #이 없고, 값이 비어 있지 않은지")
        return 1

    print(f"모델: {settings.ai_model}")
    print("키: 설정되어 있음 (값은 출력하지 않습니다)")
    if options.video:
        print("테스트 영상을 만들어 장면을 뽑는 중...")
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "sample.mp4"
                make_sample_video(path)
                frames = video_frames.extract_frames(path)
        except (video_frames.FrameExtractionError, subprocess.SubprocessError, OSError):
            print("결과: 실패 (frames) - 영상에서 장면을 뽑지 못했습니다.")
            print("확인할 것: pip install -r requirements.txt 를 다시 실행해 imageio-ffmpeg가 설치되었는지 확인하세요.")
            return 1
        print(f"장면 {len(frames)}장을 뽑았습니다.")
        images = [openai_client.ImageInput(frame, "image/jpeg") for frame in frames]
        title, kind = "연결 확인용 테스트 영상", "video"
    else:
        images = [openai_client.ImageInput(make_sample_png(), "image/png")]
        title, kind = "연결 확인용 테스트 이미지", "image"

    print("요약을 요청하는 중... (보통 몇 초)")
    try:
        result = openai_client.summarize(images, title=title, memo=None, kind=kind, client=client)
    except openai_client.AnalysisError as error:
        print(f"결과: 실패 ({error.code}) - {openai_client.message_for(error.code)}")
        hint = _HINTS.get(error.code)
        if hint:
            print(f"확인할 것: {hint}")
        return 1

    print("결과: 성공")
    print(f"걸린 시간: {result.seconds:.1f}초")
    print(f"토큰 사용량: 입력 {result.input_tokens} / 출력 {result.output_tokens}")
    print("--- 요약 ---")
    print(result.text)
    print("------------")
    print("AI 요약을 사용할 준비가 되었습니다. (키를 바꿨다면 백엔드를 다시 켜야 반영됩니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
