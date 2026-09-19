# CELL

**함께 키우는 지능, 당신의 컴퓨터에서.** 전 세계의 컴퓨터가 세포처럼 협력하는 AGI를 향한 초기 실험입니다. 현재 AGI나 검증된 자기 개선 모델은 아닙니다.

[홈페이지](https://mudlbum.github.io/cell-agent/) · [Windows v0.5 소스 ZIP](docs/downloads/cell-agent-v0.5.zip) · [Semi Cell](https://mudlbum.github.io/cell-agent/semi.html) · [무료 브라우저 대화](https://mudlbum.github.io/cell-agent/chat.html)

![Cell](docs/assets/cell-organism.webp)

## API 키 없이 시작

Windows / Python 3.10 이상: `app/start-free-model.cmd`로 무료 Qwen3-0.6B 모델과 llama.cpp를 준비하고, 모델 콘솔을 켠 채 `app/control.cmd`를 실행합니다. 자료 관리에는 모델이 필요 없습니다. 유료 LLM API 호출은 차단됩니다.

- 대화: 무료 로컬 대화, Wikipedia 검색 후 출처 포함 대화. 작은 모델의 품질에는 한계가 있습니다.
- Semi Cell: 모델 없이 모바일 메모·링크·선택한 텍스트를 저장하고 JSON으로 내보냅니다. PC에서는 격리 후 검토합니다. 실시간 동기화가 아닙니다.
- 자율 감독: PC 실행 중 채택 자료의 절차 초안, 등록 피어 자료 확인, 등록한 공개 주제의 하루 1회 검색. 결과는 검토 전 후보입니다.
- 공동 성장: 선택한 절차의 Ed25519 서명 공유, 수신 격리, 로컬 검증, 손상 재수신. 공개 중계 서버·자동 인터넷 기기 발견·모델 공동 학습은 아직 없습니다.
- 언어 학습: 별도 CPU LoRA 실험 도구. 첫 후보는 약 2.3MB였으나 대화 개선 증거가 없어 배포 모델에 적용하지 않았습니다. [실험과 설계](app/LEARNING.ko.md).

## 통제와 플랫폼

Windows Job Object 감독과 앱 비상 정지는 Cell 작업자를 종료합니다. 별도 모델 서버와 학습 도구는 각자의 종료 수단을 사용합니다. 홈페이지에는 앱 제어용 킬스위치가 없고 영상 재생 제어만 있습니다.

macOS PC 실행 엔진은 미지원입니다. Android/iOS는 Semi Cell 웹 실험판이며 실제 휴대폰 검증은 남아 있습니다. 브라우저 AI에는 WebGPU가 필요하지만 Semi 수집에는 필요하지 않습니다.

## 검증

Python 테스트 74개, 웹 테스트 14개 통과. 실제 로컬 모델 응답, Semi 격리·채택·자동 초안, Wikipedia 검색 경로 수집, 실제 CPU LoRA 16단계 학습을 확인했습니다. 품질 향상·AGI 달성을 입증한 결과는 아닙니다. [검증 기록](app/VALIDATION.md) · [설치 안내](app/README.ko.md).

홈페이지 영상은 Higgsfield 생성 자산이며 네트워크 그림은 작동 개념을 설명합니다. 실제 전 세계 접속 현황이 아닙니다.
