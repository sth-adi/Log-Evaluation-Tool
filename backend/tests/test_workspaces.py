def test_save_list_replace_delete(client):
    assert client.get("/api/workspaces").json() == []
    a = client.put("/api/workspaces", json={"name": "  Lap review ", "payload": {"v": 1, "lanes": [["rpm"]]}}).json()
    assert a["name"] == "Lap review" and a["payload"]["lanes"] == [["rpm"]]
    # the same name (any case) replaces the view instead of piling up copies
    b = client.put("/api/workspaces", json={"name": "lap REVIEW", "payload": {"v": 1, "lanes": []}}).json()
    assert b["id"] == a["id"]
    listed = client.get("/api/workspaces").json()
    assert len(listed) == 1 and listed[0]["payload"]["lanes"] == []
    other = client.put("/api/workspaces", json={"name": "Dyno", "payload": {"v": 1}}).json()
    assert {w["name"] for w in client.get("/api/workspaces").json()} == {"lap REVIEW", "Dyno"}
    assert client.delete(f"/api/workspaces/{other['id']}").status_code == 204
    assert client.delete(f"/api/workspaces/{other['id']}").status_code == 404
    assert len(client.get("/api/workspaces").json()) == 1


def test_bad_views_are_refused(client):
    assert client.put("/api/workspaces", json={"name": "   ", "payload": {}}).status_code == 422
    big = {"x": "y" * 200_000}
    assert client.put("/api/workspaces", json={"name": "big", "payload": big}).status_code == 422
    assert client.delete("/api/workspaces/..%2f..%2fx").status_code in (404, 405)
