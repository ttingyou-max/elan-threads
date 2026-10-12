"""Elan 블로그 새 글 → jang.after 쓰레드 자동 게시.

GitHub Actions 가 30분마다 실행한다.
1. 네이버 블로그 RSS 에서 아직 처리하지 않은 글을 찾는다.
2. 글 날짜(본문 첫머리 "26.10.11")와 카테고리(종목분석/시장이슈)가 같은 카드 묶음을 queue/ 에서 찾는다.
3. 카드 묶음(캐러셀) + 요약 본문을 올리고, 첫 댓글에 블로그 글 링크를 단다.
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

BASE_DIR = Path(__file__).resolve().parent
QUEUE_DIR = BASE_DIR / "queue"
STATE_PATH = BASE_DIR / "state.json"
DRAFTS_PATH = BASE_DIR / "drafts.txt"

BLOG_ID = "small_tip_plz"
RSS_URL = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
THREADS_API_BASE = "https://graph.threads.net/v1.0"
KST = timezone(timedelta(hours=9))

CATEGORY_FORMAT = {"종목분석": "stock", "시장이슈": "us"}
# 블로그 글이 올라온 뒤 이 기간 안에 카드가 큐에 들어오면 게시한다. 지나면 건너뛴다.
MATCH_WINDOW = timedelta(days=3)
TEXT_LIMIT = 500
DISCLAIMER = "※ 특정 종목의 매수·매도를 권유하는 글이 아닙니다"


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"seen": [], "posted": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_rss():
    resp = requests.get(RSS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for it in root.iter("item"):
        guid = (it.findtext("guid") or "").strip()
        desc = (it.findtext("description") or "").strip()
        m = re.match(r"(\d{2}\.\d{2}\.\d{2})", desc)
        items.append({
            "guid": guid,
            "url": guid.split("?")[0],
            "title": (it.findtext("title") or "").strip(),
            "category": (it.findtext("category") or "").strip(),
            "date": m.group(1) if m else "",
            "published": parsedate_to_datetime(it.findtext("pubDate")),
        })
    items.sort(key=lambda x: x["published"])  # 오래된 글부터 처리
    return items


def load_queue(state):
    jobs = []
    for meta_path in sorted(QUEUE_DIR.glob("*/meta.json")):
        folder = meta_path.parent.name
        if folder in state["posted"]:
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["folder"] = folder
        jobs.append(meta)
    return jobs


def match_job(item, jobs):
    fmt = CATEGORY_FORMAT.get(item["category"])
    cands = [j for j in jobs if j["date"] == item["date"] and (fmt is None or j["format"] == fmt)]
    if not cands:
        return None
    title = item["title"].replace(" ", "")
    # 종목이 둘이면 keyword 가 "서산_금호전기" 이므로 하나라도 제목에 있으면 같은 글로 본다
    by_keyword = [j for j in cands if any(k and k in title for k in j.get("keyword", "").split("_"))]
    pool = by_keyword or cands
    return min(pool, key=lambda j: j.get("queued_at", ""))


def build_texts(item, job):
    mm_dd = job["date"][3:]
    head = f"[{mm_dd} {item['category'] or '노트'}] {item['title']}"
    tail = f"전체 분석은 첫 댓글 블로그 링크에서 👇\n{DISCLAIMER}"
    summary = job.get("summary", "")
    room = TEXT_LIMIT - len(head) - len(tail) - 4
    if len(summary) > room:
        summary = summary[: max(room - 1, 0)].rstrip() + "…"
    post = "\n\n".join(p for p in (head, summary, tail) if p)
    comment = f"전체 분석은 블로그 'Elan의 노트'에서 볼 수 있습니다\n{item['url']}"
    return post, comment


def card_urls(job):
    repo = os.environ.get("GITHUB_REPOSITORY", "ttingyou-max/elan-threads")
    folder = quote(job["folder"])
    return [f"https://raw.githubusercontent.com/{repo}/main/queue/{folder}/{name}" for name in job["cards"]]


# --- Threads API -----------------------------------------------------------

def api_post(path, token, **params):
    params["access_token"] = token
    resp = requests.post(f"{THREADS_API_BASE}/{path}", params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Threads API 오류 {resp.status_code}: {resp.text}")
    return resp.json()["id"]


def wait_ready(token, container_id, tries=20):
    """이미지 컨테이너는 Threads 가 이미지를 받아갈 때까지 기다려야 게시할 수 있다."""
    for _ in range(tries):
        resp = requests.get(f"{THREADS_API_BASE}/{container_id}",
                            params={"fields": "status,error_message", "access_token": token}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "FINISHED":
            return
        if data.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"컨테이너 {container_id} 실패: {data}")
        time.sleep(5)
    raise RuntimeError(f"컨테이너 {container_id} 준비 시간 초과")


def publish_carousel(token, image_urls, text):
    children = []
    for url in image_urls:
        children.append(api_post("me/threads", token, media_type="IMAGE", image_url=url, is_carousel_item="true"))
    for cid in children:
        wait_ready(token, cid)
    carousel = api_post("me/threads", token, media_type="CAROUSEL", children=",".join(children), text=text)
    wait_ready(token, carousel)
    post_id = api_post("me/threads_publish", token, creation_id=carousel)
    print(f"[PUBLISHED] 카드 {len(children)}장 게시 (post id: {post_id})")
    return post_id


def publish_reply(token, post_id, comment, tries=3):
    """첫 댓글은 실패해도 본 게시물을 다시 올리지 않도록 여기서 오류를 삼킨다."""
    for n in range(1, tries + 1):
        try:
            time.sleep(10 * n)  # 방금 올린 게시물이 조회되기까지 잠깐 걸린다
            reply = api_post("me/threads", token, media_type="TEXT", text=comment, reply_to_id=post_id)
            wait_ready(token, reply)
            reply_id = api_post("me/threads_publish", token, creation_id=reply)
            print(f"[PUBLISHED] 첫 댓글 링크 등록 (comment id: {reply_id})")
            return reply_id
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 첫 댓글 실패 {n}/{tries}: {e}")
    return None


def main():
    test_mode = os.environ.get("TEST_MODE", "True").lower() != "false"
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not test_mode and not token:
        sys.exit("THREADS_ACCESS_TOKEN 이 없습니다.")

    state = load_state()
    items = fetch_rss()
    if not state["seen"] and not state["posted"]:
        # 첫 실행: 이미 올라와 있던 글은 건너뛰고 지금부터 올라오는 글만 처리
        state["seen"] = [it["guid"] for it in items]
        save_state(state)
        print(f"첫 실행: 기존 글 {len(items)}개를 처리한 것으로 표시했습니다.")
        return

    now = datetime.now(KST)
    jobs = load_queue(state)
    posted_any = failed = False
    for item in items:
        if item["guid"] in state["seen"]:
            continue
        job = match_job(item, jobs)
        if job is None:
            if now - item["published"] > MATCH_WINDOW:
                state["seen"].append(item["guid"])
                print(f"카드 없음, 건너뜀: {item['title']}")
            else:
                print(f"카드 대기 중: {item['date']} {item['category']} {item['title']}")
            continue

        text, comment = build_texts(item, job)
        urls = card_urls(job)
        if test_mode:
            with DRAFTS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"===== {now:%Y-%m-%d %H:%M} {job['folder']}\n{text}\n--- 첫 댓글\n{comment}\n--- 카드\n"
                         + "\n".join(urls) + "\n\n")
            print(f"[TEST_MODE] {job['folder']} 초안을 drafts.txt 에 저장 ({len(text)}자, 카드 {len(urls)}장)")
            continue

        if posted_any:
            time.sleep(30)  # 연달아 올릴 때 간격을 둔다
        try:
            post_id = publish_carousel(token, urls, text)
        except Exception as e:  # noqa: BLE001
            # 게시 전 단계에서 실패한 것이라 다음 실행에서 다시 시도해도 중복되지 않는다
            print(f"[ERROR] {job['folder']} 게시 실패, 다음 실행에서 재시도: {e}")
            failed = True
            continue
        # 게시가 끝나면 댓글보다 먼저 기록한다 (댓글 오류로 같은 글을 두 번 올리지 않도록)
        state["seen"].append(item["guid"])
        state["posted"][job["folder"]] = {"blog": item["url"], "post_id": post_id, "at": now.isoformat(timespec="seconds")}
        jobs.remove(job)
        save_state(state)
        posted_any = True
        if publish_reply(token, post_id, comment) is None:
            state["posted"][job["folder"]]["reply"] = "failed"
            save_state(state)
            failed = True

    state["seen"] = state["seen"][-200:]
    save_state(state)
    if failed:
        sys.exit("일부 게시가 실패했습니다. 위 [ERROR]/[WARN] 줄을 확인하세요.")


if __name__ == "__main__":
    main()
