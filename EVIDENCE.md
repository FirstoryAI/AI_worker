# FIRSTORY 입력 필드·페르소나·로직 근거

> 작성: 2026-10-05 (2차 개정) · 2026-10-26 수정: 쪽수(10쪽)와 의성어 규칙을 프롬프트에 맞춤 · 상태: 초안 (PM 검토 전)
> 근거 두 갈래: **(A) 유아 그림책 385권 통계** (동화 구성 쪽) · **(B) 문헌 조사** (아동 발달·부모 대화 쪽)
>
> 문헌 선정 순서: ① 국내 2020~2026 → ② 해외 2020~2026 → ③ 대체할 최근 연구가 없는 고전만 (🏛 표시)
> 판정: ✅ 지지 · △ 부분 지지 · ⚖ 엇갈림 · ❌ 반대 근거 있음 · ❓ 근거 못 찾음 · 🇰🇷 국내 근거 있음

---

## 0. 먼저 읽을 것

1. **열린 결말은 근거와 어긋난다.** 2023~2025년 실험들에서 좋은 결과를 끝까지 보여 준 이야기만 효과가 있었고([Ding 외 2023b](https://doi.org/10.1080/10888691.2023.2195182), [Sai 외 2025](https://doi.org/10.3390/bs15060733)), 국내 5세는 열린 결말을 스스로 닫으려 했다([서정숙·이효림 2021](https://doi.org/10.20926/ETPIYC.2021.6.2.2)). 사건은 닫고 의미만 연다. → §3-2
2. **동물 주인공은 "나쁘다"가 아니라 "엇갈린다".** 2022~2024년 재현 연구 3건 중 2건은 사람·동물 차이를 찾지 못했다. 국내 비교 실험은 없다. 중요한 것은 종이 아니라 **아이와 주인공 사이의 거리**다([Kucirkova & Ciesielska 2024](https://doi.org/10.1080/02702711.2024.2405483)). → §3-1
3. **가장 탄탄한 축은 감정과 그 이유를 묻는 대화, 감정코칭이다.** 국내 메타분석과 해외 무작위 연구 메타분석이 모두 지지한다. 🇰🇷
   - "그림책 + 대화·활동" 구조 자체도 국내 메타분석이 지지한다 ([고태순·안소현 2025](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003181902), [홍인표·정우영 2025](https://doi.org/10.32349/ECERR.2025.10.29.5.207)). 일대일로 읽는 맥락이 집단 읽기보다 유리했다 ([Ciesielska 외 2025](https://doi.org/10.1080/10409289.2025.2516989)). 대화식 읽기의 효과는 최근 메타분석에서도 확인된다 ([Tang 외 2026](https://doi.org/10.1016/j.ijer.2026.102963)).
4. **화면 안에 질문·효과·게임을 넣지 않는다.** 디지털 그림책 메타분석에서 돕지 못하거나 해쳤다. 질문은 부모 입으로. 현재의 "부모용 가이드" 구조가 근거에 맞다. → §3-4
5. **"질문 2개", "인터뷰 5턴"의 숫자 근거는 국내외 모두 없다.** 질문의 종류가 중요하다는 근거만 있다.

**읽을 때 주의**
- 국내 논문은 KCI에서 초록까지, 해외 논문은 초록 또는 검색 요약까지 확인했다. 본문 전체를 읽은 것은 누리과정 고시뿐이다. 외부 문서에 수치를 쓰려면 원문 대조가 필요하다.
- 국내 효과 연구는 대부분 한 기관, 20~40명 규모다. 국내 메타분석의 효과크기(1.1~1.3)는 해외(0.4~0.8)보다 훨씬 커서 그대로 믿기 어렵다. **홍보 수치로 쓰지 않는다.**
- "국내 근거 없음"은 "KCI 검색에서 못 찾음"이다. 학위논문, 육아정책연구소 보고서는 체계적으로 보지 못했다.

---

## 1. (A) 유아 그림책 통계

출처: AI Hub 「생성형AI 동화 줄거리 생성 데이터」 유아(만 4~6세) 라벨링 데이터 385권, 8,914단락.
재현: `python evals/aihub_story_stats.py <라벨링데이터 폴더>` (데이터는 저장소 밖에 둔다)

| 항목 | 유아 전체 (385권) | 사회관계 (51권) |
|---|---|---|
| 감정 요소가 있는 책 | 93% | 100% |
| 감정 첫 등장 위치 (0=처음, 1=끝) | 0.07 | 0.03 |
| 감정이 붙은 단락 | 29% | 31% |
| 인과 관계가 있는 책 | 56% | 61% |
| 결과(해결)가 라벨된 책 | 39% | 49% |
| 대사가 있는 단락 | 50% | 58% |
| 의성어·의태어(2음절 반복) 단락 | 15% | 7% |
| 지문이 "~요"로 끝나는 문장 | 51% | 73% |
| 문장 길이 (중앙값) | 7어절 | 7어절 |
| 단락당 문장 수 (중앙값) | 4 | 3 |

우리 결과물과 비교 (같은 기준):

| | 문장 길이 | 대사 있는 페이지 | 의성어·의태어 페이지 |
|---|---|---|---|
| PM 샘플 '토리' | 5어절 | 6/8 | 0/8 |
| 생성 결과 (10/2, 퓨샷 전 4편) | 5.5~7어절 | 1~5/8 | 2~3/8 |
| 생성 결과 (10/5, 퓨샷 후 2편) | 6~7어절 | 4/8 | 1/8 |

한계
- 7가지 요소는 책의 앞·중간·뒤에 고르게 분포한다. **이야기 흐름(arc)의 근거로는 쓸 수 없다.**
- "결과 라벨 없음"이 "열린 결말"을 뜻하지는 않는다.
- "실제 그림책이 이렇다"이지 "이래야 아이에게 좋다"는 아니다. 사회관계는 51권뿐이다.

---

## 2. 입력 필드 ↔ 근거 ↔ 로직

| 입력 | 판정 | 근거 | 로직에 반영 |
|---|---|---|---|
| **아이 나이** | ✅ 🇰🇷 | [김지원·정윤경 2023](https://doi.org/10.35574/KJDP.2023.9.36.3.55)(만 3~6세 152명: 정서 이해가 나이에 따라 증가), [김선희 외 2022](https://doi.org/10.15724/jslhd.2022.31.1.039)(표현하는 감정 어휘가 3·4·5세마다 다름, "기쁨" 계열이 가장 많음), [김나영·신나리 2021](https://doi.org/10.5934/kjhe.2021.30.3.389)(마음 이해가 4세와 5세 사이에 크게 달라짐), [Grosse 외 2021](https://doi.org/10.1007/s42761-021-00040-2) · 🏛 [Pons 외 2004](https://doi.org/10.1080/17405620344000022), [Wellman & Liu 2004](https://doi.org/10.1111/j.1467-8624.2004.00691.x) | 어휘와 플롯 복잡도를 가르는 실제 분기. 만 4세: 기쁨·슬픔·화·무서움 중심, 감정 원인은 눈에 보이는 사건. 오해에서 생기는 갈등은 만 5세 이상. 감정 어휘는 [황신해·김민진 2022](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002853875)의 범주별 목록에 맞춘다 |
| **상황 유형** | ✅ 🇰🇷 | 아래 줄들 | 필수 필드와 이야기 형태를 유형별로 다르게 |
| **상황 설명** (겪은 일) | ✅ | [Koh & Wang 2021](https://doi.org/10.3389/fpsyg.2021.632799), [Marshall & Reese 2022](https://doi.org/10.1016/j.jrp.2022.104262) · 🏛 [Fivush 외 2006](https://doi.org/10.1111/j.1467-8624.2006.00960.x) · (A) 인과는 책의 56%에만 | 사건 경과는 필수. 원인은 선택 (부모가 모를 수 있음). 국내 회상 대화 연구는 없어 해외 근거에 기댄다 |
| **아이의 당시 반응·감정** (겪은 일) | ✅ 필수 🇰🇷 | [조하영·윤미승 2022](https://doi.org/10.18023/kjece.2022.42.2.004)(감정코칭 부모교육 국내 메타분석), [김선희 2022](https://doi.org/10.5718/kcep.2022.16.2.3)(어머니가 지지적으로 개입할 때 유아 정서조절이 가장 높음), [England-Mason 외 2023](https://doi.org/10.1016/j.cpr.2023.102252) · (A) 사회관계 그림책 100%가 감정을 다룸 | 필수 유지. "모르겠음"이면 가이드 질문을 아이에게 직접 묻는 형태로 생성 |
| **그때 부모는 어떻게 반응했나 / 어떻게 끝났나** | ✅ (현재 폼에 없음) | 감정코칭·정서사회화 연구의 중심이 "아이의 부정적 감정에 부모가 어떻게 반응했는가" ([김선희 2022](https://doi.org/10.5718/kcep.2022.16.2.3), [England-Mason 외 2023](https://doi.org/10.1016/j.cpr.2023.102252)) | 인터뷰 질문 후보로 추가 |
| **겪을 일: 언제·어디서·누구와·어떤 순서 + 지금 보이는 걱정** | ✅ 🇰🇷 (입학 주제 1건) | [남유진·양지애 2026](https://doi.org/10.18023/kjece.2026.46.1.009)(5세 54명: 학교 정보와 주인공 감정을 함께 다룬 그림책 활동 뒤 적응 효능감 향상), [Yang 외 2022](https://doi.org/10.1186/s12887-022-03136-1), [Kerimaa 외 2023](https://doi.org/10.1111/jocn.16156) · 🏛 [Nelson 1986](https://ci.nii.ac.jp/ncid/BA0036884X) | "무슨 일이 어떤 차례로 일어나는지"와 "그때 드는 마음"을 둘 다 넣는다. "당시 반응" 대신 "지금 보이는 걱정"을 선택으로 |
| **아이 관심사** | △ | [Kucirkova 외 2021](https://doi.org/10.1016/j.ijer.2020.101710), [Kotaman & Balcı 2026](https://doi.org/10.1007/s10643-025-01976-x)(아이가 주인공인 책은 효과), [Kruse 외 2021](https://doi.org/10.1007/s10643-020-01069-x)(이름만 바꾼 책은 효과 없음) · 국내 ❓ | 소품·놀이·배경 소재로 쓴다. 얕은 개인화는 효과가 없다 |
| **아이 성향(기질)** | △ 🇰🇷 (양육 일반) | [한정인·이진숙 2024](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003121671), [유숙희·신나리 2025](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003279508)(수줍은 아이에게 침해적 양육은 정서조절을 낮춤), [조우리·신나리 2023](https://doi.org/10.5723/kjcs.2023.44.4.443)(동생 출생 반응을 기질이 예측) · 기질별로 이야기를 바꾼 효과는 ❓ | 선택 입력. 이야기가 아니라 **가이드의 전달 방식**을 바꾼다 (재촉하지 않기, 대신 말해주거나 파고들지 않기) |
| **부모가 전하고 싶은 메시지** | △ | [Ding 외 2023b](https://doi.org/10.1080/10888691.2023.2195182)("주인공처럼 해 보자"는 연결이 붙을 때 효과가 가장 큼) · 🏛 [Walker & Lombrozo 2017](https://doi.org/10.1016/j.cognition.2016.11.007) | 본문에 문장으로 넣지 않고, 가이드의 "왜 그랬을까?" 질문과 연결 질문으로 옮긴다 |

---

## 3. 재검토가 필요한 결정 (PM 상의)

### 3-1. 동물 주인공 ⚖ / 판타지 세계 △ (부분 반대)
- 동물이 불리했던 결과: [Ding 외 2023](https://doi.org/10.1016/j.appdev.2022.101498) (정직 과제) · 🏛 [Larsen 외 2017](https://doi.org/10.1111/desc.12590)
- 차이가 없었던 결과: [Russell & Cain 2022](https://doi.org/10.1016/j.jecp.2022.105392)(3~7세 179명, Larsen 재현 실패), [Russell 외 2024](https://doi.org/10.1080/10409289.2024.2303908)(이야기 기억에도 차이 없음)
- 종합: [Kucirkova & Ciesielska 2024](https://doi.org/10.1080/02702711.2024.2405483) — 사회적 학습에는 캐릭터가 친숙한지보다 **아이와의 거리가 어느 정도인지**가 중요하다
- 판타지: 🏛 [Richert & Smith 2011](https://doi.org/10.1111/j.1467-8624.2011.01603.x)(판타지 속 해결책은 현실로 덜 옮겨짐), [황윤세 2026](https://doi.org/10.23047/korea-sire.2026.8.371)(환상 그림책 읽기는 상상력만 높이고 공감에는 효과 없음)
- 국내: 비교 실험 ❓. 의인화 동물이 집·일상 배경에 나오는 것은 국내 그림책의 익숙한 형식이다([오한나 2021](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002763358)). 동물 그림책에서도 만 5세가 "나에게 적용해 보기" 반응을 보였다([오한나·김유나 2022](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002915744))

**정리**: 동물을 버릴 근거는 없다. 다만 지금 설계의 "동화적 공간 + 낯선 사건"은 거리를 너무 벌린다.
- 동물을 쓰더라도 나이·가족·유치원 같은 일상 배경과 사건을 아이와 가깝게 둔다.
- 마법으로 해결하지 않는다.
- 한국 아동 대상 비교가 없으므로 **자체 A/B 테스트 가치가 가장 큰 항목**이다. (`evals/compare_variants.py`)
- 실제 상황을 다른 캐릭터로 옮기는 것이 직접 말해 주는 것보다 낫다는 비교 연구는 ❓. 아이 본인 상황을 그대로 쓰는 방식(Social Stories)도 대규모 시험에서 효과가 약했다([Wright 외 2024](https://doi.org/10.1111/camh.12740)).

### 3-2. 열린 결말 ❌ / 교훈 미제시 △
- [Sai 외 2025](https://doi.org/10.3390/bs15060733)(유아 208명), [Ding 외 2023b](https://doi.org/10.1080/10888691.2023.2195182): 좋은 결과를 보여 준 이야기만 행동을 바꿨다
- [서정숙·이효림 2021](https://doi.org/10.20926/ETPIYC.2021.6.2.2) 🇰🇷: 5세는 불안정한 결말에서 추론과 상상으로 스스로 완결을 만들려 했다
- [김아영 외 2025](https://doi.org/10.12963/csd.250157) 🇰🇷(만 4~12세 508명): 이야기 요소 중 "결과"와 "시도"가 가장 먼저 잡힌다 · 🏛 [Mandler & Johnson 1977](https://doi.org/10.1016/0010-0285%2877%2990006-8)
- 교훈을 말하지 않는 것: 🏛 [Walker & Lombrozo 2017](https://doi.org/10.1016/j.cognition.2016.11.007)가 유일한 직접 근거. 🏛 [Narvaez 외 1999](https://doi.org/10.1037/0022-0663.91.3.477)
- [Gasser 외 2022](https://doi.org/10.1007/s10648-022-09667-4): 이야기에서 배우는 경로는 교훈 추출만이 아니다. 인물 관점에 몰입하기, 대화하기도 경로다

**정리**: **사건은 좋은 쪽으로 닫고, 의미 해석과 아이 삶으로의 연결만 연다.** 주인공이 스스로 해 본 행동과 그 결과가 이야기 안에 있어야 한다. 교훈 문장은 본문에 쓰지 않되, 가이드의 연결 질문(`bridge_question`)을 필수로 둔다.

### 3-3. 숫자 ❓
- 독서 중 질문 개수: 국내외 근거 없음. 종류에 대한 근거만 있다 — 삶과 연결되는 질문은 아이 반응을 늘리고 확인 질문은 줄인다([Wu 외 2024](https://doi.org/10.1007/s10643-024-01830-6)). 국내 관찰에서 지식 확인 질문과 다그침·재촉이 실제로 나타났다([견주연 2024](https://doi.org/10.37918/kce.2024.12.150.1)) · 🏛 [송하나·최경숙 2010](https://www.koreascience.or.kr/article/JAKO201027964151584.page)
- 인터뷰 5턴: 근거 없음. Concept Test의 완료율로 정한다

### 3-4. 화면으로 읽는 AI 생성 동화 △ (새 항목)
- [Furenes 외 2021](https://doi.org/10.3102/0034654321998074): 종이책을 그대로 화면에 옮기면 이해가 낮아진다. 어른의 중재가 디지털 기능보다 효과적
- [Bus 외 2025](https://doi.org/10.1080/10409289.2025.2571978): 화면 속 상호작용 기능의 평균 효과는 0에 가깝다. 미니게임은 해롭고, **화면에 뜨는 질문과 핫스팟은 흐름을 끊어 돕지 못한다**
- [강혜원·노진형 2021](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002729790) 🇰🇷: 어머니들은 전자그림책을 종이책과 다르게 쓴다 (읽는 계기, 시간, 상호작용)
- [조재은·임동선 2024](https://doi.org/10.12963/csd.240041) 🇰🇷: AI 생성 동화와 기존 동화의 어휘 학습 효과가 같았다 (15명)
- [황효현 2025](https://doi.org/10.25111/jcd.2025.92.19) 🇰🇷: AI 동화는 흐름은 명확하지만 **감정선과 문화적 맥락이 약하다**는 전문가 평가
- [Xu 외 2022 (대화 에이전트)](https://doi.org/10.1111/cdev.13708): AI가 질문하며 읽어 줘도 사람과 읽을 때의 이해 효과가 재현됐다 (3~6세 117명). FIRSTORY는 부모가 묻는 구조라 직접 해당하지는 않는다
- [Jin & Yuan 2025](https://doi.org/10.1016/j.ijcci.2025.100787), [Sun 외 2024](https://doi.org/10.1145/3687035), [손보혜·소효정 2022](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002878232) 🇰🇷: 부모는 사람이 검토한 AI 결과물을 받아들이고, "위험하다는 인식"이 사용 의도를 낮춘다

**정리**
- 뷰어에 탭 효과·효과음·게임·질문 팝업을 넣지 않는다. PRD의 "동화 속 대화 트리거 약 2회"는 화면에 띄우는 방식이면 근거와 어긋난다. 가이드로 옮기는 쪽이 맞다.
- 가이드는 읽기 전에 따로 본다. 읽는 흐름을 끊지 않는다.
- PDF·출력은 Could가 아니라 올려볼 만한 기능이다.
- 부모 검토 단계를 앞세우고 AI 생성임을 숨기지 않는다.
- 그림 검수: 크기·행동의 사실 오류, 위험한 행동 묘사.

---

## 4. 페르소나 규칙

### 동화 작가
| 규칙 | 근거 |
|---|---|
| 10쪽 기승전결 = 배경·주인공(1) → 발단(2) → 감정이 커지는 반복(3–5) → 이유를 말하고 스스로 해 보는 시도(6–8) → 결과(9) → 마무리(10) | [김아영 외 2025](https://doi.org/10.12963/csd.250157) 🇰🇷, [Pico 외 2021](https://doi.org/10.1044/2021_LSHSS-20-00160), [Özcan 2026](https://doi.org/10.3389/feduc.2026.1817388) · 🏛 [Mandler & Johnson 1977](https://doi.org/10.1016/0010-0285%2877%2990006-8) (요소의 순서) · 쪽수와 3–5쪽의 반복은 실제 인성 그림책 5권(행복한 유치원, 공룡 대발이, 심술 씨앗, 무례한 친구, 고미네 정리) 관찰: 9–17 펼침면, 승 구간에서 같은 문장 틀 반복 (2026-10-07) |
| "시도"와 "결과"를 분명히. 목표와 배경은 아이가 추론하기 어려우니 글·그림으로 드러낸다 | [김아영 외 2025](https://doi.org/10.12963/csd.250157) 🇰🇷 |
| 사건은 좋은 쪽으로 닫는다. 교훈 문장은 쓰지 않는다 | §3-2 |
| 주인공과 아이의 거리를 좁힌다. 일상 배경, 현실과 같은 인과, 마법 해결 금지 | §3-1 |
| 나이별 감정 어휘와 플롯 복잡도 | [김지원·정윤경 2023](https://doi.org/10.35574/KJDP.2023.9.36.3.55), [김선희 외 2022](https://doi.org/10.15724/jslhd.2022.31.1.039), [황신해·김민진 2022](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002853875), [김나영·신나리 2021](https://doi.org/10.5934/kjhe.2021.30.3.389) 🇰🇷 |
| 감정에 이름을 붙인다. 부정적 감정 단어를 피하지 않는다 | [Koh & Wang 2021](https://doi.org/10.3389/fpsyg.2021.632799), [Grosse 외 2021](https://doi.org/10.1007/s42761-021-00040-2) |
| 감정선과 한국 생활 맥락을 따로 챙긴다 | [황효현 2025](https://doi.org/10.25111/jcd.2025.92.19) 🇰🇷 |
| 대사를 페이지 절반 이상에 | §1 (A) 통계 |
| 의성어·의태어를 10쪽 중 4–6쪽에 하나씩 넣고 `**별표**`로 굵게 강조한다 | 위 그림책 5권이 의성어·의태어를 굵은 글씨·색으로 강조 (2026-10-07) · ⚖ §1 (A) 통계에서는 사회관계 책의 7% 단락에만 있어 이보다 적다 |

### 독서 코치
| 규칙 | 근거 |
|---|---|
| "사건 → 생각 → 감정"으로 인물을 이야기한다. 감정 이름에서 멈추지 않고 이유까지 | [Bergman Deitcher 외 2020](https://doi.org/10.1080/10409289.2020.1772662), [배선희·최선영 2022](https://doi.org/10.22251/jlcci.2022.22.18.877) 🇰🇷, [양소령·김현정 2024](https://doi.org/10.62783/SHSS.6.2.37) 🇰🇷 |
| 아이 삶과 연결되는 열린 질문. 지식 확인·재촉형 금지. "정답을 확인하는 질문이 아니다"를 가이드에 명시 | [Wu 외 2024](https://doi.org/10.1007/s10643-024-01830-6), [견주연 2024](https://doi.org/10.37918/kce.2024.12.150.1) 🇰🇷, [오정례 2021](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002774695) 🇰🇷, [최나야 외 2021](https://doi.org/10.21197/JCEI.12.1.4) 🇰🇷, [최나야 외 2023](https://doi.org/10.15284/kjhd.2023.30.1.121) 🇰🇷 |
| 연결 질문은 필수. 감정 인정이 먼저 | [Ding 외 2023b](https://doi.org/10.1080/10888691.2023.2195182), [조하영·윤미승 2022](https://doi.org/10.18023/kjece.2022.42.2.004) 🇰🇷, [England-Mason 외 2023](https://doi.org/10.1016/j.cpr.2023.102252) |
| 한국 양육 문화에 맞춘 감정코칭 표현. 서구 문장 직역 금지 | [이희숙 외 2025](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003248928) 🇰🇷 |
| 수줍은 아이: 재촉하지 않기, 대신 말해주거나 파고들지 않기 | [유숙희·신나리 2025](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003279508) 🇰🇷, [한정인·이진숙 2024](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003121671) 🇰🇷 |
| 동생 출생: "힘들 것"을 전제하지 않는다 | [조우리·신나리 2023](https://doi.org/10.5723/kjcs.2023.44.4.443) 🇰🇷 |
| 질문은 적게. AI가 만든 질문을 고르고 고치는 부담이 사용자에게 남는다 | [김나영·김민진 2026](https://doi.org/10.22154/JCLE.27.1.4) 🇰🇷 |
| 질문은 화면이 아니라 부모 입으로 | [Bus 외 2025](https://doi.org/10.1080/10409289.2025.2571978), [Furenes 외 2021](https://doi.org/10.3102/0034654321998074) |
| 질문 유형은 감정·인과·예측으로 태깅한다 (효과 근거가 아니라 분류 틀) | [Xu 외 2022 (FairytaleQA)](https://aclanthology.org/2022.acl-long.34/) |

누리과정과의 연결: 의사소통 목표 "책이나 이야기를 통해 상상하기를 즐긴다", 사회관계 목표 "자신을 이해하고 존중한다 / 다른 사람과 사이좋게 지낸다", 그리고 "유아 중심과 놀이 중심" ([2019 개정 누리과정](https://www.law.go.kr/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99/%EC%9C%A0%EC%B9%98%EC%9B%90%EA%B5%90%EC%9C%A1%EA%B3%BC%EC%A0%95)). 교훈 주입이나 퀴즈식 질문은 이 방향과 어긋난다.

---

## 5. 로직 구성

```
상황 유형
 ├─ 이미 겪은 일 ── 필수: 사건 경과, 아이의 당시 반응
 │                  인터뷰 후보: 부모는 어떻게 반응했나, 어떻게 끝났나, 짐작하는 이유
 │                  이야기: 비슷한 일을 겪는 주인공 → 스스로 시도 → 좋은 쪽으로 닫힌 결과
 │                  가이드: 감정 → 이유 → 연결 질문(필수)
 ├─ 앞으로 겪을 일 ─ 필수: 언제·어디서·누구와·어떤 순서
 │                  선택: 지금 보이는 걱정, 비슷한 과거 경험
 │                  이야기: 일상 배경 + 실제 순서 + 그때 드는 마음, 끝까지 보여 줌
 │                  가이드: 예측 질문 중심
 └─ 알려줄 주제 ──── 필수: 전달 메시지
                    가이드: 메시지로 향하는 "왜 그랬을까?" 질문 + 연결 질문

나이   → 감정 어휘, 플롯 복잡도 (만 4세 / 만 5~6세)
성향   → 가이드 전달 방식
관심사 → 소품·놀이·배경 소재
화면   → 책 화면에는 글·그림만. 질문은 가이드(읽기 전)로 분리
```

---

## 6. 근거를 찾지 못한 것

**국내외 모두 없음**
- 독서 중 질문의 적정 개수
- 실제 상황을 다른 캐릭터로 옮긴 맞춤 이야기 vs 직접 말해 주기 vs 일반 그림책 비교
- "교훈을 말하지 않고 설명하게 한다"의 2020년 이후 재현
- 기질에 따라 이야기나 읽기 방식을 달리한 효과
- 친구 갈등·등원 거부·이사·반려동물 죽음을 그림책으로 다룬 4~6세 무작위 연구
- AI 생성 맞춤 그림책의 정서·행동 효과 (어휘 효과 1건뿐)

**국내에 없음 (해외 근거에 기댐)**
- 동물 vs 사람 주인공 비교 실험
- 개인화 그림책의 효과
- 부모–자녀가 지난 일을 되짚는 대화의 효과
- 화면과 종이로 읽을 때의 부모–자녀 대화 비교

"치료" 표현은 쓰지 않는다.

---

## 7. 출처

링크 안내: 해외 학술지 링크는 논문 소개 페이지로 연결된다. 초록은 누구나 볼 수 있지만 본문은 유료이거나 기관 로그인이 필요한 경우가 많다.

검증 수준: **원문** 본문 확인 · **KCI 초록** KCI 레코드와 초록 확인 · **초록** 초록 확인 · **요약** 검색 도구가 보여 준 요약으로 확인 · **2차** 다른 문헌 경유

**데이터·공식 문서**
- 한국지능정보사회진흥원(NIA) AI Hub (2023). 생성형AI 동화 줄거리 생성 데이터. — §1 통계는 이 데이터를 활용한 NIA 사업 결과물 기반이다. 원문은 저장소·프롬프트에 포함하지 않는다. [https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71696](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71696) (원자료)
- 교육부 (2019). 유치원 교육과정(2019 개정 누리과정). 교육부고시 제2019-189호. — 목표 문구까지 원문 확인. 영역별 세부 내용표는 미대조. [https://www.law.go.kr/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99/%EC%9C%A0%EC%B9%98%EC%9B%90%EA%B5%90%EC%9C%A1%EA%B3%BC%EC%A0%95](https://www.law.go.kr/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99/%EC%9C%A0%EC%B9%98%EC%9B%90%EA%B5%90%EC%9C%A1%EA%B3%BC%EC%A0%95) (원문)

**국내 (2020~2026)**
- 고태순·안소현 (2025). 그림책을 활용한 독서치료 프로그램의 효과에 대한 메타분석. 독서치료연구, 17(1), 1–17. — 국내 22편 메타분석, 전 연령. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003181902](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003181902) (KCI 초록)
- 홍인표·정우영 (2025). 그림책을 활용한 유아 탄력성 증진 프로그램의 효과에 대한 메타분석. 유아교육학논집, 29(5), 207–232. — 국내 13편, 주로 만 5세. [https://doi.org/10.32349/ECERR.2025.10.29.5.207](https://doi.org/10.32349/ECERR.2025.10.29.5.207) (KCI 초록)
- 오한나 (2021). 창작 그림책에 나타난 동물 등장인물의 특성 및 인간과의 관계 분석 연구. 어린이문학교육연구, 22(3), 109–144. — 그림책 98권 내용 분석. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002763358](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002763358) (KCI 초록)
- 오한나·김유나 (2022). 함께 그림책 읽기에서 나타난 유아의 비판적 사고 반응 탐색: 동물 등장인물을 중심으로. 열린유아교육연구, 27(6), 231–260. — 만 5세 18명, 관찰, 비교집단 없음. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002915744](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002915744) (KCI 초록)
- 황윤세 (2026). 교사와 함께 환상 그림책 읽기 활동이 유아의 상상력과 정서적 공감에 미치는 영향. 국제교류와 융합교육, 6(2), 371–385. — 유아 38명, 실험·통제. [https://doi.org/10.23047/korea-sire.2026.8.371](https://doi.org/10.23047/korea-sire.2026.8.371) (KCI 초록) — 이 링크는 논문 페이지가 아니라 서지 정보만 보여 준다. 본문은 KCI에서 제목으로 검색
- 조재은·임동선 (2024). AI-생성동화를 활용한 개별 맞춤형 책읽기 활동이 미취학 아동의 어휘 학습에 미치는 영향. Communication Sciences & Disorders, 29(4), 686–702. — 3–6세 15명, 3주. [https://doi.org/10.12963/csd.240041](https://doi.org/10.12963/csd.240041) (KCI 초록)
- 최나야·최지수·노보람·오태성 (2021). 그림책을 활용한 부모-자녀 말놀이 프로그램이 책 읽기 상호작용, 만 4세 유아의 이야기 이해와 음운론적 인식에 미치는 영향. 인지발달중재학회지, 12(1), 71–102. — 만 4세 44명, 실험·통제, 가정 12주. [https://doi.org/10.21197/JCEI.12.1.4](https://doi.org/10.21197/JCEI.12.1.4) (KCI 초록)
- 최나야·최지수·정수지·김효은·박상아 (2023). 유아의 기초문해력에 영향을 미치는 가정의 물리적 문해환경 및 양적·질적 책 읽기 상호작용. 인간발달연구, 30(1), 121–138. — 만 4세와 어머니 125쌍. [https://doi.org/10.15284/kjhd.2023.30.1.121](https://doi.org/10.15284/kjhd.2023.30.1.121) (KCI 초록)
- 견주연 (2024). 그림책 읽기 과정에서 나타난 유아기 자녀를 둔 두 어머니의 읽기 특징 탐색. 한국영유아보육학, (150), 1–26. — 만 5세와 어머니 2쌍, 질적. [https://doi.org/10.37918/kce.2024.12.150.1](https://doi.org/10.37918/kce.2024.12.150.1) (KCI 초록)
- 오정례 (2021). 유아와 어머니의 그림책 함께 읽기 발화 양상 연구. 리터러시 연구, 12(5), 475–510. — 만 6세와 어머니 3쌍. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002774695](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002774695) (KCI 초록)
- 배선희·최선영 (2022). 그림책을 활용한 정서표현활동이 유아의 정서지능과 공감능력에 미치는 영향. 학습자중심교과교육연구, 22(18), 877–894. — 만 3세 24명, 8주. [https://doi.org/10.22251/jlcci.2022.22.18.877](https://doi.org/10.22251/jlcci.2022.22.18.877) (KCI 초록)
- 양소령·김현정 (2024). 문제해결에 기초한 그림책 토의 활동이 유아의 정서지능 및 또래유능성에 미치는 영향. 인문사회과학연구, 6(2), 615–632. — 만 5세 38명, 8주. [https://doi.org/10.62783/SHSS.6.2.37](https://doi.org/10.62783/SHSS.6.2.37) (KCI 초록)
- 조하영·윤미승 (2022). 메타분석을 이용한 감정코칭 부모교육프로그램 연구의 체계적 리뷰. 유아교육연구, 42(2), 87–105. — 국내 13편. [https://doi.org/10.18023/kjece.2022.42.2.004](https://doi.org/10.18023/kjece.2022.42.2.004) (KCI 초록)
- 이희숙·김동주·김경숙 (2025). 감정코칭 부모교육 프로그램이 영·유아기 어머니의 양육효능감, 자아존중감 및 부모-자녀 의사소통에 미치는 효과: 혼합연구. 한국콘텐츠학회 논문지, 25(9), 746–756. — 만 2–4세 자녀 어머니 30명, 7주. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003248928](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003248928) (KCI 초록)
- 김선희 (2022). 어머니의 정서사회화 유형에 따른 유아 정서조절의 차이. 육아정책연구, 16(2), 3–27. — 만 4–6세 170명과 어머니, 횡단. [https://doi.org/10.5718/kcep.2022.16.2.3](https://doi.org/10.5718/kcep.2022.16.2.3) (KCI 초록)
- 남유진·양지애 (2026). 그림책을 활용한 유초연계활동이 5세 유아의 초등학교 적응 효능감과 정서지능에 미치는 영향. 유아교육연구, 46(1), 223–244. — 5세 54명, 실험·비교, 12회. [https://doi.org/10.18023/kjece.2026.46.1.009](https://doi.org/10.18023/kjece.2026.46.1.009) (KCI 초록)
- 조우리·신나리 (2023). 동생 출생에 따른 영유아의 문제행동 변화 유형과 예측 변인. 아동학회지, 44(4), 443–456. — 임신부 202명, 3시점 종단. [https://doi.org/10.5723/kjcs.2023.44.4.443](https://doi.org/10.5723/kjcs.2023.44.4.443) (KCI 초록)
- 김지원·정윤경 (2023). 유아기 연령에 따른 얼굴표정 정서읽기, 정서이해, 정서단어 이해의 발달 및 관련성. 한국심리학회지: 발달, 36(3), 55–70. — 만 3–6세 152명. [https://doi.org/10.35574/KJDP.2023.9.36.3.55](https://doi.org/10.35574/KJDP.2023.9.36.3.55) (KCI 초록)
- 김선희·박은실·신혜정 (2022). 3–5세 유아의 정서어휘 표현에 관한 연구. 언어치료연구, 31(1), 39–50. — 3세 25명, 4세 30명, 5세 30명. [https://doi.org/10.15724/jslhd.2022.31.1.039](https://doi.org/10.15724/jslhd.2022.31.1.039) (KCI 초록)
- 황신해·김민진 (2022). 유아 정서어휘 검사도구 개발 및 타당화 연구. 열린유아교육연구, 27(3), 153–181. — 정서 범주별 어휘 75문항. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002853875](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002853875) (KCI 초록)
- 김나영·신나리 (2021). 유아의 마음이론 발달과 공감능력 간의 관계. 한국생활과학회지, 30(3), 389–399. — 만 3–5세 132명. [https://doi.org/10.5934/kjhe.2021.30.3.389](https://doi.org/10.5934/kjhe.2021.30.3.389) (KCI 초록)
- 김아영·김영현·박다현·조유리·임동선 (2025). 연령과 이야기 산출 방식에 따른 아동의 이야기 문법 발달 양상. Communication Sciences & Disorders, 30(4), 696–707. — 만 4–12세 508명. [https://doi.org/10.12963/csd.250157](https://doi.org/10.12963/csd.250157) (KCI 초록)
- 서정숙·이효림 (2021). 그림책의 결말에 대한 5세 유아의 의미구성과 이해. 영유아교육: 이론과 실천, 6(2), 27–54. — 5세 14명, 질적. [https://doi.org/10.20926/ETPIYC.2021.6.2.2](https://doi.org/10.20926/ETPIYC.2021.6.2.2) (KCI 초록)
- 한정인·이진숙 (2024). 유아의 행동억제기질이 내재화 행동문제에 미치는 영향: 어머니 과보호의 조절효과. 정서·행동장애연구, 40(3), 65–84. — 3–5세 387명, 횡단. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003121671](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003121671) (KCI 초록)
- 유숙희·신나리 (2025). 유아의 수줍음이 정서조절에 미치는 영향: 어머니의 과보호적 양육태도의 매개효과. 인간발달연구, 32(4), 141–158. — 만 4–5세. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003279508](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003279508) (KCI 초록)
- 강혜원·노진형 (2021). 유아기 자녀를 둔 어머니의 종이그림책과 전자그림책에 대한 인식 및 활용실태 비교. 한국유아교육연구, 23(2), 89–109. — 어머니 202명 설문. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002729790](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002729790) (KCI 초록)
- 김나영·김민진 (2026). 생성형 AI 활용 경험에 따른 유아교사의 그림책 읽기 질문과 AI 활용 인식 분석. 어린이문학교육연구, 27(1), 77–103. — 교사 8명. [https://doi.org/10.22154/JCLE.27.1.4](https://doi.org/10.22154/JCLE.27.1.4) (KCI 초록)
- 황효현 (2025). 생성형 AI와 인간 작가 간의 창작 동화의 서사적 일관성 비교 연구. 커뮤니케이션 디자인학연구, 92, 281–293. — 동화 각 1편, 전문가 12명 블라인드 평가. [https://doi.org/10.25111/jcd.2025.92.19](https://doi.org/10.25111/jcd.2025.92.19) (KCI 초록)
- 손보혜·소효정 (2022). 유아 대상 AI활용 학습콘텐츠의 수용요인에 관한 부모 인식 연구. 교육정보미디어연구, 28(3), 763–789. — 부모 설문. [https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002878232](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002878232) (KCI 초록)

**해외 (2020~2026)**
- Ding, Tay, Chua & Cheng (2023). Can classic moral stories with anthropomorphized animal characters promote children's honesty? J. Applied Developmental Psychology, 85. — 3–6세, 싱가포르. [https://doi.org/10.1016/j.appdev.2022.101498](https://doi.org/10.1016/j.appdev.2022.101498) (요약)
- Russell & Cain (2022). The animals in moral tales. J. Experimental Child Psychology, 219. — 3–7세 179명. [https://doi.org/10.1016/j.jecp.2022.105392](https://doi.org/10.1016/j.jecp.2022.105392) (요약)
- Russell, Wang & Cain (2024). Children's Narrative Retells: The Influence of Character Realism and Storybook Theme. Early Education and Development, 35(8). — 3–7세 171명. [https://doi.org/10.1080/10409289.2024.2303908](https://doi.org/10.1080/10409289.2024.2303908) (요약)
- Kucirkova & Ciesielska (2024). The Distance Between the Story Character and the Reader. Reading Psychology, 46(2). — 체계적 문헌고찰. [https://doi.org/10.1080/02702711.2024.2405483](https://doi.org/10.1080/02702711.2024.2405483) (요약)
- Kucirkova, Gattis, Spargo, Seisdedos de Vega & Flewitt (2021). An empirical investigation of parent-child shared reading of digital personalized books. Int. J. Educational Research, 105. — 어머니와 3–4세 26쌍. [https://doi.org/10.1016/j.ijer.2020.101710](https://doi.org/10.1016/j.ijer.2020.101710) (요약)
- Kruse, Faller & Read (2021). Can Reading Personalized Storybooks to Children Increase Their Prosocial Behavior? Early Childhood Education Journal, 49(2).. [https://doi.org/10.1007/s10643-020-01069-x](https://doi.org/10.1007/s10643-020-01069-x) (요약)
- Kotaman & Balcı (2026). The Impact of Personalized Storybooks on Children's Altruistic Sharing Behavior. Early Childhood Education Journal, 54(3). — 5–6세 315명 무작위. [https://doi.org/10.1007/s10643-025-01976-x](https://doi.org/10.1007/s10643-025-01976-x) (요약)
- Wright 외 (2024). ASSSIST-2: a pragmatic randomised controlled trial of Social Stories. Child and Adolescent Mental Health, 30(1). — 4–11세 자폐 아동 249명. [https://doi.org/10.1111/camh.12740](https://doi.org/10.1111/camh.12740) (초록)
- Bergman Deitcher, Aram, Khalaily-Shahadi & Dwairy (2020). Promoting Preschoolers' Mental-Emotional Conceptualization and Social Understanding. Early Education and Development, 32(4). — 평균 75개월 116명 무작위. [https://doi.org/10.1080/10409289.2020.1772662](https://doi.org/10.1080/10409289.2020.1772662) (요약)
- Ciesielska, Kucirkova & Thomson (2025). How the Type and Context of Children's Storybook Reading Relate to Select Empathy Skills: A Meta-Analysis. Early Education and Development, 36(8). — 21편. [https://doi.org/10.1080/10409289.2025.2516989](https://doi.org/10.1080/10409289.2025.2516989) (요약)
- Wu 외 (2024). Teacher-child talk in Shared-book Reading with Preschoolers. Early Childhood Education Journal, 53(8). — 중국 유아 교실. [https://doi.org/10.1007/s10643-024-01830-6](https://doi.org/10.1007/s10643-024-01830-6) (요약)
- England-Mason, Andrews, Atkinson & Gonzalez (2023). Emotion socialization parenting interventions targeting emotional competence in young children. Clinical Psychology Review. — 무작위 시험 15편 메타분석. [https://doi.org/10.1016/j.cpr.2023.102252](https://doi.org/10.1016/j.cpr.2023.102252) (요약)
- Koh & Wang (2021). Mother–Child Reminiscing About Emotionally Negative Events and Children's Long-Term Mental Health. Frontiers in Psychology, 12. — 유럽계·중국계 미국인 어머니와 4.5세, 종단. [https://doi.org/10.3389/fpsyg.2021.632799](https://doi.org/10.3389/fpsyg.2021.632799) (초록)
- Marshall & Reese (2022). Growing Memories. J. Research in Personality, 99. — 어머니 115명 회상 훈련, 자녀 21세 추적. [https://doi.org/10.1016/j.jrp.2022.104262](https://doi.org/10.1016/j.jrp.2022.104262) (요약)
- Yang 외 (2022). Effects of advance exposure to an animated surgery-related picture book on preoperative anxiety. BMC Pediatrics. — 3–6세 131명 무작위. [https://doi.org/10.1186/s12887-022-03136-1](https://doi.org/10.1186/s12887-022-03136-1) (요약)
- Kerimaa 외 (2023). Effectiveness of interventions used to prepare preschool children and their parents for day surgery. J. Clinical Nursing, 32(9–10). — 무작위 연구 15편. [https://doi.org/10.1111/jocn.16156](https://doi.org/10.1111/jocn.16156) (초록)
- Grosse, Streubel, Gunzenhauser & Saalbach (2021). Let's Talk About Emotions. Affective Science, 2(2). — 4–11세 123명. [https://doi.org/10.1007/s42761-021-00040-2](https://doi.org/10.1007/s42761-021-00040-2) (초록)
- Pico 외 (2021). Interventions Designed to Improve Narrative Language in School-Age Children: A Systematic Review With Meta-Analyses. LSHSS, 52(4). — 26편. [https://doi.org/10.1044/2021_LSHSS-20-00160](https://doi.org/10.1044/2021_LSHSS-20-00160) (초록)
- Özcan (2026). The effect of dialogic reading interventions on narrative skills in the preschool period. Frontiers in Education, 11. — 16편 메타분석. [https://doi.org/10.3389/feduc.2026.1817388](https://doi.org/10.3389/feduc.2026.1817388) (초록)
- Xu 외 (2022). Fantastic Questions and Where to Find Them: FairytaleQA. ACL 2022. — 서사 7요소 틀. [https://aclanthology.org/2022.acl-long.34/](https://aclanthology.org/2022.acl-long.34/) (원문)
- Ding, Cheng, Cheng & Heyman (2023). An assessment of when moral stories promote children's honesty. Applied Developmental Science, 28(3). — 중국 3–6세. [https://doi.org/10.1080/10888691.2023.2195182](https://doi.org/10.1080/10888691.2023.2195182) (요약)
- Sai, Zheng, Tang, Sai & Liu (2025). Moral Stories Can Promote Honesty in Chinese Young Children. Behavioral Sciences, 15(6). — 유아 208명. [https://doi.org/10.3390/bs15060733](https://doi.org/10.3390/bs15060733) (초록)
- Gasser, Dammert & Murphy (2022). How Do Children Socially Learn from Narrative Fiction. Educational Psychology Review, 34(3). — 통합 리뷰. [https://doi.org/10.1007/s10648-022-09667-4](https://doi.org/10.1007/s10648-022-09667-4) (초록)
- Furenes, Kucirkova & Bus (2021). A Comparison of Children's Reading on Paper Versus Screen: A Meta-Analysis. Review of Educational Research, 91(4). — 1–8세, 39개 연구. [https://doi.org/10.3102/0034654321998074](https://doi.org/10.3102/0034654321998074) (요약)
- Bus, Kucirkova, Ten Braak & Ciesielska (2025). Which Interactive Features in Children's Digital Picture Books Promote Reading Comprehension? A Meta-Analysis. Early Education and Development, 37(2). — 2–8세 20편. [https://doi.org/10.1080/10409289.2025.2571978](https://doi.org/10.1080/10409289.2025.2571978) (요약)
- Xu 외 (2022). Dialogue with a conversational agent promotes children's story comprehension via enhancing engagement. Child Development, 93(2). — 3–6세 117명 무작위. [https://doi.org/10.1111/cdev.13708](https://doi.org/10.1111/cdev.13708) (초록)
- Sun 외 (2024). Exploring Parent's Needs for Children-Centered AI to Support Preschoolers' Interactive Storytelling and Reading Activities. Proc. ACM HCI, 8(CSCW2). — 부모 17명, 질적. [https://doi.org/10.1145/3687035](https://doi.org/10.1145/3687035) (초록)
- Jin & Yuan (2025). Understanding the needs and preferences of children and parents in AI-generated images for stories. Int. J. Child-Computer Interaction, 46. — 부모–아이 13쌍. [https://doi.org/10.1016/j.ijcci.2025.100787](https://doi.org/10.1016/j.ijcci.2025.100787) (요약)
- Tang, Lau & Du (2026). Effects and moderators of dialogic reading on children's reading literacy: A three-level meta-analysis. Int. J. Educational Research, 137. — 64편. [https://doi.org/10.1016/j.ijer.2026.102963](https://doi.org/10.1016/j.ijer.2026.102963) (요약)

**고전 🏛 (대체할 최근 연구 없음)**
- Larsen, Lee & Ganea (2017). Do storybooks with anthropomorphized animal characters promote prosocial behaviors in young children? Developmental Science, 21(3). — 논쟁의 출발점. Russell & Cain 2022가 재현 실패. [https://doi.org/10.1111/desc.12590](https://doi.org/10.1111/desc.12590) (초록)
- Richert & Smith (2011). Preschoolers' Quarantining of Fantasy Stories. Child Development, 82(4). — 2020년 이후 유아 대상 재현 없음. [https://doi.org/10.1111/j.1467-8624.2011.01603.x](https://doi.org/10.1111/j.1467-8624.2011.01603.x) (2차)
- 송하나·최경숙 (2010). 어머니의 그림책 읽기 상호작용이 아동의 정서적 경험과 이야기 회상에 미치는 영향. 아동학회지, 31(1), 219–234. — 만 6세 60쌍. 이후 양적 재검증 없음, 견주연 2024가 같은 방향. [https://www.koreascience.or.kr/article/JAKO201027964151584.page](https://www.koreascience.or.kr/article/JAKO201027964151584.page) (초록)
- Fivush, Haden & Reese (2006). Elaborating on Elaborations. Child Development, 77(6). — 지난 일 되짚기 연구의 종합. Koh & Wang 2021, Marshall & Reese 2022가 결론 유지를 보여 줌. [https://doi.org/10.1111/j.1467-8624.2006.00960.x](https://doi.org/10.1111/j.1467-8624.2006.00960.x) (초록)
- Nelson (1986). Event Knowledge: Structure and Function in Development. Erlbaum. — 유아가 사건을 순서(스크립트)로 이해한다는 이론적 토대. [https://ci.nii.ac.jp/ncid/BA0036884X](https://ci.nii.ac.jp/ncid/BA0036884X) (2차)
- Pons, Harris & de Rosnay (2004). Emotion comprehension between 3 and 11 years. European J. Developmental Psychology, 1(2). — 정서 이해 검사의 원전. 김지원·정윤경 2023이 한국 유아에게 그대로 사용. [https://doi.org/10.1080/17405620344000022](https://doi.org/10.1080/17405620344000022) (초록)
- Wellman & Liu (2004). Scaling of Theory-of-Mind Tasks. Child Development, 75(2). — 마음 이해 발달 순서의 원전. [https://doi.org/10.1111/j.1467-8624.2004.00691.x](https://doi.org/10.1111/j.1467-8624.2004.00691.x) (초록)
- Mandler & Johnson (1977). Remembrance of things parsed. Cognitive Psychology, 9(1). — 이야기 문법의 원전. 김아영 외 2025가 한국 아동에게 같은 범주 적용. [https://doi.org/10.1016/0010-0285%2877%2990006-8](https://doi.org/10.1016/0010-0285%2877%2990006-8) (초록)
- Walker & Lombrozo (2017). Explaining the moral of the story. Cognition, 167. — '교훈을 말하지 않고 설명하게 한다'의 유일한 직접 근거. 2020년 이후 재현 없음. [https://doi.org/10.1016/j.cognition.2016.11.007](https://doi.org/10.1016/j.cognition.2016.11.007) (초록)
- Narvaez, Gleason, Mitchell & Bentley (1999). Moral theme comprehension in children. J. Educational Psychology, 91(3). — 초등 3·5학년도 주제를 성인만큼 뽑지 못함. [https://doi.org/10.1037/0022-0663.91.3.477](https://doi.org/10.1037/0022-0663.91.3.477) (초록)
