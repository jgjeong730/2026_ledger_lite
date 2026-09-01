# WORKFLOW

이 문서는 **"어떻게 이 프로젝트를 진행하는지"** 를 기록한다. 무엇을 만들었는지는
[README.md](../README.md), 무엇이 실패하고 무엇을 배웠는지는 [RETROSPECTIVE.md](../RETROSPECTIVE.md),
왜 이 앱을 만드는지는 [PROJECT_BRIEF.md](PROJECT_BRIEF.md)에 있다. 이 문서는 그 세 문서와
겹치지 않게, 반복되는 개발 루프와 관례만 다룬다.

## 1. 개발 루프

모든 변경이 아래 다섯 단계를 반복한다.

1. **요청** — 자연어 한 문장으로 요청 ("거래내역에 카테고리별 합계 표 추가해줘")
2. **코드 수정** — Claude Code가 관련 파일을 읽고 고침
3. **로컬 검증** — 관련 pytest 실행 + `streamlit run`으로 로컬 서버를 띄워 브라우저에서
   실제로 클릭해 확인 (아래 2절 참고). UI 변경은 코드가 맞아 보여도 반드시 화면으로 확인한다 —
   RETROSPECTIVE 4장에서 "버그처럼 보인 것"이 실제로는 레이아웃 문제였던 사례가 반복됐다.
4. **커밋** — `<페이지/영역>: <변경 요약>` 형식으로 커밋 (3절 참고)
5. **푸시 → 자동 배포 → 실사이트 확인** — `main`에 푸시하면 Streamlit Community Cloud가
   자동 재배포한다. 배포 설정 자체는 README "Streamlit Community Cloud 배포" 절 참고.

확인해서 마음에 들면 끝, 아니면 1번으로 돌아가 다시 — 커밋 로그에 남은 대부분의 변경이
이 루프 한 바퀴다.

## 2. 로컬 실행 & 테스트

```bash
# 테스트 (전체 또는 파일 단위)
.venv/Scripts/python -m pytest tests/ -v
.venv/Scripts/python -m pytest tests/test_dashboard_service.py -v

# 문법만 빠르게 확인 (서버 안 띄우고)
.venv/Scripts/python -m py_compile app/main.py app/pages/6_대시보드.py

# 로컬 서버로 브라우저 검증 — 다른 프로세스와 안 겹치게 매번 새 포트 사용
.venv/Scripts/python -m streamlit run app/main.py --server.headless true --server.port 8599
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8599

# 확인 끝나면 프로세스 정리
kill %1   # 또는 PID로 taskkill/Stop-Process
```

카카오 로그인처럼 실제 계정 인증이 필요한 경로는 자동화로 못 덮는다 — 요청 구성까지는
`requests`를 모킹한 오프라인 테스트로, 실제 로그인/전송은 사용자가 앱에서 직접 확인한다.

## 3. 커밋 컨벤션

- **작은 변경(대부분)**: 제목 한 줄로 끝. `<페이지/영역>: <변경 요약>`
  예) `거래내역: 카테고리별 합계 표 추가`, `은행이체 수동입력: 대분류/소분류를 한 박스에 좌우 배치`
- **큰 변경(구조 변경·마이그레이션·회고 등)**: 제목 + 본문(무엇을·왜)에 이어
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 푸터를 붙인다.
  예) `1512e3c Supabase(Postgres) 영구 저장소 전환` 커밋 참고.

## 4. 배포 문제 생기면 확인하는 순서

RETROSPECTIVE 2장에서 반복 확인된 순서:

1. **`git status` / `git log`** — 로컬에서 완성한 코드를 커밋·푸시하는 걸 깜빡한 적이 있다
   ("로컬에서 됐다"와 "배포됐다"는 다르다).
2. **캐시성 문제 의심** — 커밋엔 분명히 있는데 `ImportError`가 나면 Streamlit Cloud 모듈
   캐시 문제일 수 있다. Reboot 전에 그로 인한 부작용(예: 영속 저장소 미설정 시 데이터 유실)이
   없는지부터 확인한다 — `SUPABASE_DB_URL`이 설정돼 있으면 Reboot은 안전하다.
3. **그다음에야 로직** — 위 둘을 먼저 배제한 뒤 코드를 의심한다.

## 5. AI 협업 관례

- 자주 반복되는 안전한 명령(테스트, 로컬 서버 실행/종료, git commit/push 등)은
  `.claude/settings.local.json` 허용목록에 등록해 매번 승인을 묻지 않게 한다.
- 민감한 파일(`.env`, `data/*.db`, `data/kakao_token.json`, 실거래 백업 엑셀)은
  프로젝트 시작 시점부터 `.gitignore`에 넣어둔다 — 데이터가 실제로 쌓이기 시작한 뒤 막으면 늦는다.
- 페이지 개편처럼 큰 변경도 사용자가 기존 방식을 더 선호하면 그대로 되돌린다 — "새로운 게
  항상 낫다"고 가정하지 않는다.

## 6. 문서 지도

| 문서 | 다루는 것 |
|---|---|
| [README.md](../README.md) | 이 앱이 뭔지, 구조, 기술 스택, 시작하기, 배포 설정 |
| [RETROSPECTIVE.md](../RETROSPECTIVE.md) | 무엇이 실패했고 왜 그랬는지, 재사용할 교훈 |
| [docs/PROJECT_BRIEF.md](PROJECT_BRIEF.md) | 이 앱을 만드는 배경과 요구사항 |
| docs/WORKFLOW.md (이 문서) | 어떻게 진행하는지 — 개발 루프, 커밋/배포 관례 |

---
2026-09-01 작성
