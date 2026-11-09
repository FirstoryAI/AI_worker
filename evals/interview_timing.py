"""진짜 모델로 인터뷰 답 한 번이 얼마나 걸리는지 (#82, #83). uv run python evals/interview_timing.py <datasets/inputs 이름>
체크포인트는 임시 폴더. 서버 안에서 위기 신호 검사와 다음 질문 만들기를 동시에 돌린 시간이다."""
import dataclasses, json, sys, tempfile, time, uuid
from pathlib import Path
from fastapi.testclient import TestClient
from firstory import server
server.config = dataclasses.replace(server.config, checkpoint_db=Path(tempfile.mkdtemp()) / "ck.db", internal_token="t")
H = {"X-Internal-Token": "t"}
name = sys.argv[1]
data = json.loads(Path(f"datasets/inputs/{name}.json").read_text()); answers = data.pop("scripted_answers"); data.pop("_note", None)
data["parent"] = {"response": None, "concern": None, "message": None, "message_direction": None}
rows = []
with TestClient(server.app) as c:
    tid = str(uuid.uuid4())
    t = time.time(); r = c.post(f"/v1/threads/{tid}/interview/start", headers=H, json={"run_id": str(uuid.uuid4()), "context": data}).json()
    rows.append(("start", time.time() - t, r["type"], None))
    i = 0
    while r["type"] == "question" and i < 8:
        a = "아니요, 동화 만들러 갈게요" if r["question"].startswith("동화를 만들 준비가") else (answers[i] if i < len(answers) else "잘 모르겠어요")
        i += 1
        t = time.time(); r = c.post(f"/v1/threads/{tid}/interview/answer", headers=H, json={"answer": a}).json()
        rows.append((f"answer{i}", time.time() - t, r["type"], (r.get("safety") or {}).get("level")))
print(json.dumps({"name": name, "rows": rows}, ensure_ascii=False))
