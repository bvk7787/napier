from napier import scenarios as scen

RACK = dict(rows=6, hp=208, geometry=dict(grid=[2, 2], case_rows=["1U", "3U", "3U"]))
MODS = [
    dict(slug="a", name="A", hp=10, format="3U", role="voice", owned=True, at=["row 2, hp 1"]),
    dict(slug="b", name="B", hp=8, format="3U", role="voice", owned=True, at=["row 2, hp 11"]),
    dict(slug="l", name="L", hp=14, format="1U", role="utility", owned=True, at=["row 1, hp 1", "row 4, hp 1"]),
    dict(slug="w", name="W", hp=6, format="3U", role="midi", owned=False, at=[]),
]


def test_geometry_marks_1u_rows_and_cases():
    g = scen.geometry(RACK)
    assert g["row_format"] == {1: "1U", 2: "3U", 3: "3U", 4: "1U", 5: "3U", 6: "3U"}
    assert g["cases"]["bottom-right"] == dict(rows=[4, 5, 6], hp=[105, 208])


def test_move_add_remove_and_change_labels():
    r = scen.resolve(dict(name="t", remove=["b"], place=[dict(slug="a", at=["row 3, hp 1"]),
                                                        dict(slug="w", at=["row 2, hp 11"])]), MODS, RACK)
    ch = {m["slug"]: m["change"] for m in r["modules"]}
    assert ch == {"a": "moved", "w": "new", "l": "kept"}
    assert [m["slug"] for m in r["removed"]] == ["b"]
    assert r["problems"] == []


def test_problems_overlap_seam_format_and_unknown():
    r = scen.resolve(dict(place=[dict(slug="w", at=["row 2, hp 13"]),      # overlaps B
                                 dict(slug="a", at=["row 5, hp 100"]),      # crosses 104/105
                                 dict(slug="l", at=["row 2, hp 150", "row 4, hp 1"]),  # 1U in a 3U row
                                 dict(slug="zzz", at=["row 1, hp 1"])]), MODS, RACK)
    text = " | ".join(r["problems"])
    assert "overlaps" in text and "seam" in text and "1U module in a 3U row" in text and "unknown module zzz" in text


def test_partial_removal_lists_the_copy_that_left():
    r = scen.resolve(dict(place=[dict(slug="l", at=["row 1, hp 1"])]), MODS, RACK)
    assert r["removed"][0]["at"] == ["row 4, hp 1"]


def test_checks_power_pairs_and_free_space():
    usage = {"a": {"pairs_with": ["b"]}, "l": {"keep_near": ["a"]}}
    r = scen.resolve(dict(place=[dict(slug="b", at=["row 3, hp 50"])]), MODS, RACK, usage)
    power = {"a": {"plus12": 100, "minus12": 50, "plus5": 0}, "b": {"plus12": 2950, "minus12": 0, "plus5": 0}}
    cases = {"top-left": {"limits": {"plus12": 3000, "minus12": 3000, "plus5": 1500}}}
    ck = scen.checks(r, power, RACK, usage, cases, far_cm=10)
    assert ck["power"]["top-left"]["pct"]["plus12"] == 102
    assert any("over the 3000 mA supply" in w for w in ck["warnings"])
    assert [(p["a"], p["b"]) for p in ck["far_pairs"]] == [("a", "b")]
    assert 32 < ck["far_pairs"][0]["cm"] < 33 and not ck["far_pairs"][0]["cross_case"]
    assert ck["pairs"][-1]["keep_near"] is True and ck["pairs"][-1]["cm"] < 10
    assert "top-left row 3: 1-49, 58-104" in ck["fragmented"]
    assert ck["free"]["top-left"][2] == [[11, 104]]


def test_distance_ok_moves_a_far_pair_to_accepted():
    usage = {"a": {"pairs_with": ["b"]}, "b": {"distance_ok": ["a"]}}
    r = scen.resolve(dict(place=[dict(slug="b", at=["row 3, hp 50"])]), MODS, RACK, usage)
    ck = scen.checks(r, {}, RACK, usage, {}, far_cm=10)
    assert ck["far_pairs"] == []
    assert [(p["a"], p["b"]) for p in ck["accepted_far"]] == [("a", "b")] and ck["accepted_far"][0]["accepted"]


def test_geometry_defaults_to_one_case_and_names_grids():
    g = scen.geometry(dict(rows=2, hp=84))
    assert g["order"] == ["main"] and g["cases"]["main"] == dict(rows=[1, 2], hp=[1, 84])
    assert set(g["row_format"].values()) == {"3U"}
    g = scen.geometry(dict(rows=2, hp=208), dict(grid=[2, 1]))
    assert g["order"] == ["left", "right"] and g["cases"]["right"]["hp"] == [105, 208]
    g = scen.geometry(dict(rows=9, hp=252), dict(grid=[3, 3], case_rows=["1U", "3U", "3U"]))
    assert g["order"][:3] == ["r1c1", "r1c2", "r1c3"] and g["row_format"][4] == "1U"
    g = scen.geometry(dict(rows=4, hp=104), dict(grid=[1, 2], names=["upper", "lower"]))
    assert g["order"] == ["upper", "lower"]
    assert scen.geometry(dict(rows=5, hp=104), dict(grid=[1, 2]))["order"] == ["main"]   # 5 rows don't split in 2
