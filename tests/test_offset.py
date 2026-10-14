from napier.sources import offset_trusted, page_number_in


def test_prefixed_footers_count_as_page_numbers():
    assert page_number_in(["Filter Depth  0-18", "", "pg 48"]) == 48
    assert page_number_in(["TITLE", "body", "Page 12"]) == 12
    assert page_number_in(["TITLE", "body", "p. 7"]) == 7


def test_plain_and_trailing_numbers_still_work():
    assert page_number_in(["Header", "text", "14"]) == 14
    assert page_number_in(["12 The OXI ONE MKII Manual", "body"]) == 12     # leading, in a header
    assert page_number_in(["The OXI ONE MKII Manual 13", "body"]) == 13
    assert page_number_in(["no numbers here"]) is None
    assert page_number_in(["Header", "text", "Strymon TimeLine MX user manual  23"]) == 23


def test_offset_needs_enough_pages_and_a_majority():
    assert offset_trusted(26, 27)
    assert offset_trusted(3, 5)
    assert not offset_trusted(2, 25)   # TimeLine MX before the fix: guessed 81
    assert not offset_trusted(1, 1)    # too few numbered pages to trust
    assert not offset_trusted(2, 2)
    assert not offset_trusted(0, 0)


def test_direction_marks_are_ignored():
    footer = "\u202dPlanar\u202c\u202d2\u202c \u202dManual\u202c \u202d11\u202c"
    assert page_number_in(["\u202dTITLE\u202c", "body", footer]) == 11


def test_footer_wins_over_a_wrapped_header():
    lines = ["[8] X OUT", "Outputs a voltage on Planar", "2", "body", "Planar", "2 Manual 11"]
    assert page_number_in(lines) == 11
