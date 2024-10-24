import pytest

from undate.dateformat.edtf.parser import edtf_parser

# for now, just test that valid dates can be parsed

testcases = [
    "1984",
    "1984-05",
    "1984-12",
    "1001-03-30",
    "1000/2000",
    "1000-01/2000-05-01",
    # level 1
    "Y170000002",
    "-Y170000002",
    "2001-21",  # spring 2001
    # negative year
    "-1985",
    # qualifiers
    "1984?",
    "2004-06~",
    "2004-06-11%",
    # unspecified digits from right
    "201X",
    "20XX",
    "2004-XX",
    "1985-04-XX",
    "1985-XX-XX",
    # open ended intervals
    "1985-04-12/..",
    "1985-04/..",
    "../1985-04-12",
    "/1985-04-12",
]


@pytest.mark.parametrize("date_string", testcases)
def test_should_parse(date_string):
    assert edtf_parser.parse(date_string)


error_cases = ["1984-13", "Y1702"]


@pytest.mark.parametrize("date_string", error_cases)
def test_should_error(date_string):
    with pytest.raises(Exception):
        edtf_parser.parse(date_string)
