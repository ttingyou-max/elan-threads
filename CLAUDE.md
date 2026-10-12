# Elan 블로그 → 쓰레드(jang.after) 자동 게시

블로그(blog.naver.com/small_tip_plz)에 새 글이 올라오면, 같은 글의 요약 카드 묶음을 jang.after 쓰레드에 올리고 첫 댓글에 블로그 글 링크를 단다.
저장소: https://github.com/ttingyou-max/elan-threads (**공개 저장소**. 쓰레드가 카드 이미지를 공개 주소로 받아가야 해서 공개로 둔다. 토큰은 Secrets 에 있어 공개되지 않는다)
실제로 도는 것은 GitHub Actions 쪽이다. 작업 전 `git pull`.

## 흐름
1. (PC) 블로그 작업실에서 빌드가 끝나면 `python queue_job.py <작업 폴더>` → 카드 8장 + meta.json 을 `queue/<폴더>/` 에 넣고 push.
2. (사용자) 네이버 블로그에 글을 직접 올린다 (네이버는 글쓰기 API 가 없음).
3. (GitHub) `elan_poster.py` 가 30분마다 RSS 확인 → 글 첫머리 날짜("26.10.11")와 카테고리(종목분석=stock, 시장이슈=us)가 같은 큐 항목을 찾아 게시. 같은 날 같은 형식이 여럿이면 종목명/주제가 제목에 있는 쪽, 없으면 먼저 넣은 쪽.
   - 블로그 글이 올라온 뒤 3일 안에 카드가 안 들어오면 그 글은 건너뛴다.
4. 게시 형식: 본문 `[MM.DD 카테고리] 블로그 제목` + caption.txt [설명] 요약 + "전체 분석은 첫 댓글 블로그 링크에서 👇" + 면책 문구 (500자 이내). 첫 댓글 = 블로그 글 주소.

## 파일
- `elan_poster.py` 게시 봇 / `queue_job.py` PC 에서 큐 넣기 / `state.json` 처리한 글(seen)과 게시 기록(posted)
- 일정: `.github/workflows/elan_cron.yml` (30분마다). 끄기: schedule 블록 주석 처리 후 push.
- 토큰: GitHub Secrets `ELAN_THREADS_ACCESS_TOKEN` (jang.after 계정, 장기 토큰 60일 유효 → 만료 전에 새로 받아 교체).
- 로컬 테스트: TEST_MODE 기본값 True → 게시하지 않고 drafts.txt 에 초안을 쓴다. 키 값은 절대 출력하지 않는다.
- 인스타 자동 게시: 계정을 프로페셔널(크리에이터)로 바꾼 뒤 추가 예정.

## 현재 상태 (바뀌면 날짜와 함께 고친다)
- 2026-10-12: 코드 작성, 로컬 테스트 통과. **GitHub 저장소 생성 + jang.after 토큰 등록 대기 중.**
  - 큐에 `ISSUE_261011_호남반도체클러스터` 가 들어 있고 그 블로그 글은 미처리로 남겨 둠 → 토큰 등록 후 첫 실행에서 10/11 시장이슈 글이 첫 게시물로 올라간다 (10/14 22:44 까지).
