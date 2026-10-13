"""PC 에서 실행: 빌드가 끝난 작업 폴더의 카드를 큐에 넣고 GitHub 에 올린다.

    python queue_job.py "C:/Users/Ryzen 3/claude/blog_elan/elan_studio/jobs/261007_펩트론"
    python queue_job.py <job> --no-push   (복사만)
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
QUEUE_DIR = BASE_DIR / "queue"
KST = timezone(timedelta(hours=9))


def read_summary(caption_path):
    """caption.txt 의 [설명] 에서 고정 문구를 뺀 요약 줄만 가져온다."""
    if not caption_path.exists():
        return ""
    lines, inside = [], False
    for line in caption_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = s == "[설명]"
            continue
        if inside and s and not s.startswith("전체 분석은") and not s.startswith("※"):
            lines.append(s)
    return "\n".join(lines)


def git(*args):
    subprocess.run(["git", *args], cwd=BASE_DIR, check=True)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    job = Path(sys.argv[1]).resolve()
    spec = json.loads((job / "spec.json").read_text(encoding="utf-8"))
    cards = sorted((job / "out" / "cards").glob("*.png"))
    if not cards:
        sys.exit(f"카드가 없습니다: {job / 'out' / 'cards'}")

    dst = QUEUE_DIR / job.name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for c in cards:
        shutil.copy2(c, dst / c.name)

    name = spec.get("name", job.name)
    meta = {
        "date": spec["date"],
        "format": spec["format"],
        "keyword": name.rsplit("_", 1)[0],
        "summary": read_summary(job / "caption.txt"),
        "cards": [c.name for c in cards],
        "queued_at": datetime.now(KST).isoformat(timespec="seconds"),
    }
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"큐에 넣음: {job.name} (카드 {len(cards)}장, {meta['date']} {meta['format']})")

    if "--no-push" in sys.argv:
        return
    git("pull", "--rebase", "--autostash", "-q")  # 카드를 다시 넣을 때 바뀐 파일이 있어도 받아온다
    git("add", "queue")
    git("commit", "-q", "-m", f"queue: {job.name}")
    git("push", "-q")
    print("GitHub 에 올렸습니다. 블로그 글이 올라오면 30분 안에 쓰레드에 게시됩니다.")


if __name__ == "__main__":
    main()
