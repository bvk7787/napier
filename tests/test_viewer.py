import json

from napier.viewer import build_data, render

EXPORT = {
    "rack": {"name": "Actual Rack", "rows": 6, "hp": 208, "geometry": {"grid": [2, 2], "case_rows": ["1U", "3U", "3U"]},
             "modified": "2026-09-27", "url": "https://example.test/r"},
    "modules": [
        {"slug": "a", "name": "A", "vendor": "V", "hp": 10, "format": "3U", "role": "voice", "racked": True,
         "owned": True, "at": ["row 2, hp 1"], "power": {"plus12": 50, "minus12": 10, "plus5": 0},
         "power_manual": {"plus12": 60, "minus12": 5, "plus5": None, "page": 3},
         "usage": {"job": "lead voice", "status": "keep", "notes": ["n"], "pairs_with": ["b"]}},
        {"slug": "b", "name": "B</script>", "hp": 8, "format": "3U", "role": "filter", "racked": False,
         "owned": True, "at": []},
    ],
    "challenges": [{"id": "c001", "date": "2026-10-06", "title": "t", "outcome": "rejected", "modules": ["a"]}],
    "usage_cases": {"top-left": {"mode": "voices", "limits": {"plus12": 3000, "minus12": 3000, "plus5": 1500}}},
    "scenarios": {"plan": {"name": "Plan", "date": "2026-10-10", "description": "d", "notes": [],
                           "modules": [{"slug": "a", "at": ["row 3, hp 1"], "change": "moved", "name": "A", "hp": 10},
                                       {"slug": "w", "at": ["row 2, hp 1"], "change": "new", "name": "W", "hp": 6,
                                        "format": "3U", "role": "midi", "owned": False}],
                           "removed": [], "problems": []}},
}


def test_build_data_actual_scenarios_power_and_wishlist_cards():
    d = build_data(EXPORT, generated="now")
    assert list(d["layouts"]) == ["actual", "plan"]
    assert d["layouts"]["actual"]["modules"] == [{"slug": "a", "at": ["row 2, hp 1"], "change": "kept"}]
    assert d["modules"]["a"]["power"] == {"plus12": 60, "minus12": 10, "plus5": 0}
    assert d["modules"]["w"]["owned"] is False            # scenario-only module still gets a card
    assert d["geometry"]["row_format"]["4"] == "1U"
    assert d["cases"]["top-left"]["limits"]["plus12"] == 3000


def test_render_is_safe_and_titled():
    html = render(EXPORT, generated="now")
    assert html.startswith("<!doctype html>") and "<title>Actual Rack</title>" in html
    titled = render(dict(EXPORT, title="My <Rack>", owner="sam"), generated="now")
    assert "<title>My &lt;Rack&gt;</title>" in titled and '"owner": "Sam"' in titled
    assert "B</script>" not in html and "B\\u003c/script\\u003e" in html
    frag = render(EXPORT, standalone=False, generated="now")
    assert not frag.startswith("<!doctype") and frag.startswith("<title>")
    data = frag.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["layouts"]["plan"]["modules"][1]["change"] == "new"


def test_page_loads_nothing_unless_web_fonts_asked():
    page = render(EXPORT)
    assert "http://" not in page.replace('xmlns="http://www.w3.org', "") and "https://fonts" not in page
    assert "fonts.googleapis.com" in render(EXPORT, web_fonts=True)


def test_rack_data_cannot_break_out_of_the_page():
    import copy
    ex = copy.deepcopy(EXPORT)
    ex["rack"]["name"] = "__DATA__</script><img src=x onerror=alert(1)>"
    ex["title"] = "</script><script>alert(2)</script>"
    ex["rack"]["url"] = "javascript:alert(3)"
    ex["modules"][0]["name"] = "<!--<script>alert(4)</script>"
    page = render(ex)
    head, _, rest = page.partition('<script id="rack-data" type="application/json">')
    data, _, _ = rest.partition("</script>")
    assert "<" not in data and ">" not in data                    # nothing in the data can open or close a tag
    assert "<img" not in page and "<script>alert" not in page
    assert "/^https?:" in page                                    # rack links are http(s) only
    assert json.loads(data)["rack"]["name"].startswith("__DATA__")  # and the value survives intact
