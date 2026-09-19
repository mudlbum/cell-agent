# 홈페이지 배포와 도메인 연결

## 저장소 구성

`docs/`는 빌드가 필요 없는 HTML/CSS/JS 사이트다. GitHub Pages의 배포 소스는 `main` 브랜치의 `/docs`로 지정한다. `.nojekyll`을 포함한다. 앱 상태·API 키·개인 파일을 정적 사이트에 올리지 않는다.

로컬 미리 보기:

```powershell
python -m http.server 8780 --bind 127.0.0.1 --directory docs
```

이 서버는 개발용이다. 공개 홈페이지는 GitHub Pages에서 제공하며 로컬 에이전트를 호스팅하거나 원격 제어하지 않는다.

## 도메인 후보

1. `growwithcell.com`: 사용자가 Cell과 함께 성장한다는 의미가 명료하다. 우선 추천.
2. `cellweave.ai`: 각자의 경험을 연결해 엮는다는 이미지가 있다.
3. `cellcommons.org`: 공동으로 검증하고 나누는 프로젝트의 성격을 강조한다.

이 이름들은 브랜드 제안이며 등록 가능 여부, 가격, 상표 충돌을 확인한 결과가 아니다. 구매 직전에 등록처의 실제 상태와 갱신 비용을 확인한다. 도메인을 구매하지 않았다면 저장소의 Pages 기본 주소를 먼저 사용한다.

## 도메인을 산 뒤

1. GitHub 계정의 Pages 설정에서 도메인을 검증한다. 표시된 TXT 레코드를 DNS에 추가하고 확인한다.
2. 이 저장소 → Settings → Pages → Custom domain에 사용할 도메인을 등록한다.
3. `www`를 사용하는 경우 등록처 DNS에서 `www` CNAME을 `mudlbum.github.io`로 지정한다. 저장소 이름 `/cell-agent`를 CNAME에 붙이지 않는다.
4. 루트 도메인도 사용할 경우 GitHub 공식 안내의 A/ALIAS/ANAME 설정을 적용한다. 와일드카드 DNS는 사용하지 않는다.
5. DNS와 인증서 발급이 완료되면 Enforce HTTPS를 켜고 실제 접속 및 다운로드를 확인한다.

도메인을 GitHub에 먼저 등록한 뒤 DNS를 연결한다. DNS 전파·인증서 발급에는 시간이 걸릴 수 있다. 최신 값과 순서는 [GitHub 공식 문서](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)를 따른다.

## 배포 검증

- 데스크톱 및 390px 모바일 뷰포트에서 디자인 확인, 가로 넘침 수정.
- 작업 단계 전환과 비상 정지 표시 체험, FAQ, 설치 문서 이동 확인.
- 상대 경로 자산과 ZIP 다운로드, SHA-256 체크섬 대조.
- 홈페이지는 실제 AI 실행처럼 보이게 오인시키지 않도록 미리보기와 지원 상태를 표기한다.
- macOS/Android/iOS의 실기기 실행, 공개 인터넷 피어 운영과 실제 모델 API 호출은 별도 검증 대상이다.
