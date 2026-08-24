import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_submit_and_search_recipe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Submit
        submit_payload = {
            "id": "rec_test_001",
            "problem": {
                "errorSignature": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
                "runtime": "python",
                "packages": {},
                "description": "Attempting to add int and str directly without cast."
            },
            "solution": {
                "summary": "Cast integer to string using str(val) or format string.",
                "codeDiff": "--- old.py\n+++ new.py\n@@ -1,1 +1,1 @@\n-res = 5 + 'test'\n+res = str(5) + 'test'",
                "instructions": ["Use str(x)"]
            },
            "reproduction": {
                "script": "res = 5 + 'test'",
                "testSuite": "def test_fix(): assert str(5) + 'test' == '5test'"
            },
            "primarySource": "https://docs.python.org/3/library/functions.html#func-str"
        }
        res = await ac.post("/api/v1/recipes/submit", json=submit_payload)
        assert res.status_code == 201
        created = res.json()
        assert created["id"] == "rec_test_001"
        assert created["evidence"]["verificationStatus"] == "VERIFIED"

        # Search
        search_res = await ac.post("/api/v1/recipes/search", json={
            "errorSignature": "unsupported operand type",
            "runtime": "python"
        })
        assert search_res.status_code == 200
        found = search_res.json()
        assert len(found) > 0
        assert found[0]["id"] == "rec_test_001"

@pytest.mark.asyncio
async def test_recipe_detail_html_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/recipes/rec_test_001")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "rec_test_001" in res.text
        assert "Sandbox Execution Evidence" in res.text
