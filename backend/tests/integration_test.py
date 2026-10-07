"""End-to-end integration test for the MVP core loop, per docs/11 Phase 18 and
docs/12 (Create → Upload → Process → Course Brain → Importance → Recommendation →
Learn → Answer → Mastery update → Recommendation/Review). Run against a live server.
"""
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=30)
    username = f"integration-{uuid.uuid4().hex[:16]}"
    r = client.post("/auth/register", json={"username": username, "password": f"Integration-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    print("PASS 0 register isolated integration user", r.json()["data"]["id"])

    # 1. Create course
    r = client.post("/courses", json={"name": "集成测试课程", "exam_date": "2026-08-20",
                                      "preferences": {"learning_mode": "EXPLANATION_FIRST"}})
    assert r.status_code == 200, r.text
    course_id = r.json()["data"]["id"]
    print("PASS 1 create course", course_id)

    # 2. Upload material
    with open("data/materials/sample_computer_network.txt", "rb") as f:
        r = client.post(f"/courses/{course_id}/materials",
                        data={"type": "REAL_EXAM"},
                        files={"file": ("sample.txt", f, "text/plain")})
    assert r.status_code == 200, r.text
    material = r.json()["data"]
    print("PASS 2 upload material", material["id"], material["status"])

    # 3. Wait for processing to finish (worker is threaded)
    import time
    for _ in range(50):
        r = client.get(f"/materials/{material['id']}")
        status = r.json()["data"]["status"]
        if status in ("COMPLETED", "FAILED"):
            break
        time.sleep(0.3)
    assert status == "COMPLETED", f"material not completed: {status}"
    print("PASS 3 material processed -> COMPLETED")

    # 4. Course READY + knowledge structure
    r = client.get(f"/courses/{course_id}/dashboard")
    data = r.json()["data"]
    assert data["course"]["status"] == "READY", data
    print("PASS 4 course READY, progress:", data["progress"])

    r = client.get(f"/courses/{course_id}/knowledge")
    domains = r.json()["data"]["domains"]
    total_units = sum(len(d["children"]) for d in domains)
    assert total_units > 0, "no study units"
    print(f"PASS 5 knowledge: {len(domains)} domains, {total_units} units")

    # 5. Recommendation
    r = client.get(f"/courses/{course_id}/recommendation")
    rec = r.json()["data"]
    assert rec and rec["study_unit"]["id"], rec
    suid = rec["study_unit"]["id"]
    print("PASS 6 recommendation ->", rec["study_unit"]["title"][:20])

    # 6. Start session, explanation, question
    r = client.post(f"/study-units/{suid}/start", json={})
    session_id = r.json()["data"]["session_id"]
    print("PASS 7 start session", session_id)

    r = client.get(f"/learning-sessions/{session_id}/explanation")
    assert r.json()["data"]["content"], r.text
    print("PASS 8 explanation generated")

    r = client.get(f"/learning-sessions/{session_id}/next-question")
    q = r.json()["data"]["question"]
    print("PASS 9 next question:", q["content"][:20])

    # 7. Answer wrong -> mastery should NOT be mastered, review item appears
    r = client.post(f"/questions/{q['id']}/answer",
                    json={"session_id": session_id, "answer": "__WRONG__", "time_spent": 10})
    answer = r.json()["data"]
    assert answer["correct"] is False, answer
    print("PASS 10 answer wrong, next_action:", answer["next_action"], "mastery:", answer["knowledge_update"]["mastery_status"])

    # Answer correctly (look up correct answer) -> must be graded as correct
    correct_answer = answer["correct_answer"]
    assert correct_answer, "question has no stored answer to verify against"
    r = client.post(f"/questions/{q['id']}/answer",
                    json={"session_id": session_id, "answer": correct_answer, "time_spent": 5})
    answer2 = r.json()["data"]
    assert answer2["correct"] is True, f"correct answer must grade True: {correct_answer=} {answer2=}"
    print("PASS 11 answer correct:", answer2["correct"], "mastery:", answer2["knowledge_update"]["mastery_status"])

    # 8. Review items should include weak/learning units
    r = client.get(f"/courses/{course_id}/review")
    items = r.json()["data"]["items"]
    print("PASS 12 review items:", len(items), [i["title"][:12] for i in items[:3]])

    # 9. Re-recommendation still works after learning
    r = client.get(f"/courses/{course_id}/recommendation")
    assert r.json()["data"]["study_unit"]["id"]
    print("PASS 13 recommendation after learning ->", r.json()["data"]["study_unit"]["title"][:20])

    # 10. Progress updated
    r = client.get(f"/courses/{course_id}/progress")
    prog = r.json()["data"]
    print("PASS 14 progress:", prog)

    print("\nALL INTEGRATION TESTS PASSED")


if __name__ == "__main__":
    main()
