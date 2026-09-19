# CELL

**작은 시작. 함께 자라는 가능성.**

대화로 작업을 맡기고, 지식을 찾고 검증하는 절차를 남기며, 사용자가 선택한 경험을 서명된 패키지로 공유하는 실험적 AI 에이전트입니다.

[홈페이지](https://mudlbum.github.io/cell-agent/) · [설치 안내](https://mudlbum.github.io/cell-agent/install.html) · [Windows 실험판 ZIP](docs/downloads/cell-agent-v0.3.zip)

![Cell — illustrative organism](docs/assets/cell-organism.webp)

## 현재 기능

- 대화별 기록과 제한된 후속 문맥, 텍스트 첨부, 진행 이벤트와 명령 승인.
- 한 작업 안에서 역할을 나누는 하위 에이전트와 호출·시간·자원 제한.
- 출처와 탐색 방법, 검증 기준, 실패 시 대체 경로를 저장하고 사용자 근거로 평가.
- Ed25519 서명과 SHA-256으로 선택한 절차 교환, 수신 격리, 로컬 후보 등록, 손상 패키지 재수신.
- Windows Job Object 감독, 비상 정지, 중단 잠금, 파일 도구 변경 백업.

## 빠른 시작 — Windows

Python 3.10 이상을 준비한 뒤:

```powershell
cd app
python -X utf8 dashboard.py
```

또는 `app/control.cmd`를 실행합니다. 기본 대화 화면에서 **고정 시나리오 데모**를 선택하면 API 키 없이 런타임을 체험할 수 있습니다. 데모는 입력한 질문을 해결하는 LLM이 아닙니다.

실제 작업은 GPT-6 Astra API 접근 권한과 API 키가 필요하며 비용이 발생할 수 있습니다. 키는 로컬 화면에서만 입력하세요. 이 배포에서는 실제 유료 API 호출을 테스트하지 않았습니다.

선택적 피어 공유:

```powershell
python -m pip install -r requirements-network.txt
python share_server.py
```

기본 공유 서버는 루프백 읽기 전용 피드입니다. 다른 기기의 피드에 연결하려면 HTTPS 주소와 직접 확인한 공개 키가 필요합니다. 제어 서버 8765를 외부에 노출하지 마세요.

## 플랫폼 상태

| 환경 | 상태 |
|---|---|
| Windows | Python 소스 실험판, 로컬 검증 |
| macOS | 런타임 미지원, 별도 감독·권한 구현 필요 |
| Android / iOS | 앱 미출시, 컴패니언 설계 단계 |
| 웹 | 반응형 소개 및 설치 안내 |

[플랫폼 확장 계획](app/PLATFORMS.ko.md)을 참고하세요. 홈페이지가 모바일에서 보인다고 모바일 실행 엔진이 구현된 것은 아닙니다.

## 검증

```powershell
cd app
python -X utf8 -m unittest test_cell_agent test_control test_workspace -q
```

Windows / Python 3.10.10에서 **52개 테스트 통과**. 피어 테스트는 선택 의존성 `cryptography`가 필요합니다. 두 로컬 노드의 실제 HTTP 교환, 서명/해시 변조 거부, 버전 롤백 거부, 격리/후보 등록, 손상 복원을 포함합니다. [상세 검증 기록](app/VALIDATION.md).

## 명확한 한계

Cell은 새로운 LLM, AGI, 블록체인이나 자동 백신이 아닙니다. 현재의 성장은 검증된 경험과 절차의 축적·재사용이며 모델 가중치는 학습하지 않습니다. 지능 향상을 입증한 벤치마크가 없습니다. 피어의 코드를 원격 실행하지 않습니다.

프로세스 감독은 적대적 코드에 대한 OS 샌드박스가 아닙니다. 승인한 명령은 현재 사용자 권한으로 실행됩니다. 비상 정지는 이미 끝난 파일 변경이나 외부 서비스 요청을 취소하지 않습니다. [운영·권한 설명](app/README.ko.md).

이 저장소에는 개인 대화, 작업 상태, API 키, 서명 개인 키를 포함하지 않습니다. 서명 키는 각 설치 시 로컬에서 생성합니다.

## 디렉터리

- `app/`: 실행 코드, UI, 테스트와 문서
- `docs/`: GitHub Pages 정적 홈페이지와 다운로드 파일
- `DEPLOYMENT.ko.md`: 홈페이지 배포 및 도메인 연결

메인 비주얼은 Higgsfield로 생성했습니다. 출처와 작업 ID는 [ASSETS.md](docs/ASSETS.md)에 기록했습니다. 공개 소스의 재배포·기여 라이선스 정책은 별도 LICENSE가 추가되기 전까지 확정되지 않았습니다.
