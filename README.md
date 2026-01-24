# airpermit-law-alert

정적 웹에서 보는 **법령/고시/의안 변경 알림** 페이지.

## Pages
- /updates.html : 전체 목록 + 변경 강조
- /changes.html : 변경사항만

## Auto Update
GitHub Actions가 **매시 정각** 실행되어 아래 파일을 갱신합니다.
- public/updates.json`n- public/changes.json`n- public/health.json`n- data/state.json`n
웹에는:
- 갱신시각(KST, 요일+밀리초)
- 정각 대비 지연
- 마지막 성공 후 경과시간
- 75분 초과 시 빨간 경고

## Security
- .env/_.env/*.env 절대 커밋 금지
- API/SMTP 비번은 GitHub Secrets로만 설정

## GitHub Secrets
### API
- LAW_OC`n- ASSEMBLY_KEY`n
### Email Alert (fail/stale)
- ALERT_SMTP_HOST`n- ALERT_SMTP_PORT`n- ALERT_SMTP_USER`n- ALERT_SMTP_PASS`n- ALERT_TO = help@airpermit.work
- ALERT_FROM (optional)


