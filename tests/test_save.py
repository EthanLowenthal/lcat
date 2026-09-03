import json

import pytest

from lcat.loaders import load
from lcat.save import SaveError, save, serialize

CSV = "id,name,score\n3,Charlie,10\n1,alpha,200\n2,Bravo,30\n"


def test_delimited_round_trips():
    doc = load(CSV, "csv")
    assert serialize(doc) == CSV


def test_delimited_quotes_an_edited_cell():
    doc = load(CSV, "csv")
    doc.rows[0][1] = "Charlie, jr\nsecond line"
    assert serialize(doc) == (
        'id,name,score\n3,"Charlie, jr\nsecond line",10\n1,alpha,200\n2,Bravo,30\n'
    )


def test_tsv_keeps_its_delimiter():
    doc = load("a\tb\n1\t2\n", "tsv")
    doc.rows[0][0] = "9"
    assert serialize(doc) == "a\tb\n9\t2\n"


def test_no_header_is_not_invented_on_the_way_out():
    doc = load("1,2\n3,4\n", "csv", has_header=False)
    assert serialize(doc) == "1,2\n3,4\n"


def test_json_records_keep_their_types():
    doc = load('[{"id": 1, "host": "web-01", "up": true}]', "json")
    doc.rows[0][0] = "7"
    doc.rows[0][1] = "web-02"
    assert json.loads(serialize(doc)) == [{"id": 7, "host": "web-02", "up": True}]


def test_json_string_column_stays_a_string():
    doc = load('[{"zip": "01730"}, {"zip": "02139"}]', "json")
    doc.rows[0][0] = "94110"
    assert json.loads(serialize(doc)) == [{"zip": "94110"}, {"zip": "02139"}]


def test_json_lines_are_written_one_per_line():
    doc = load('{"a": 1}\n{"a": 2}\n', "json")
    doc.rows[1][0] = "5"
    assert serialize(doc) == '{"a":1}\n{"a":5}\n'


def test_json_object_round_trips_as_an_object():
    doc = load('{"name": "lcat", "stars": 3}', "json")
    doc.rows[1][1] = "4"
    assert json.loads(serialize(doc)) == {"name": "lcat", "stars": 4}


def test_json_list_of_lists_round_trips():
    doc = load("[[1, 2], [3, 4]]", "json")
    doc.rows[0][0] = "9"
    assert json.loads(serialize(doc)) == [[9, 2], [3, 4]]


def test_markdown_is_written_verbatim():
    doc = load("# Title\n\nbody\n", "md")
    doc.text = "# Other\n"
    assert serialize(doc) == "# Other\n"


def test_save_writes_the_file(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    doc = load(CSV, "csv", path)
    doc.rows[0][1] = "Charles"
    assert save(doc) == path
    assert path.read_text() == CSV.replace("Charlie", "Charles")


def test_save_leaves_no_temporary_file_behind(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    doc = load(CSV, "csv", path)
    save(doc)
    assert [p.name for p in tmp_path.iterdir()] == ["data.csv"]


def test_save_needs_a_path():
    with pytest.raises(SaveError, match="stdin"):
        save(load(CSV, "csv"))


def test_save_refuses_a_truncated_table(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(CSV)
    doc = load(CSV, "csv", path).head(1)
    with pytest.raises(SaveError, match="max-rows"):
        save(doc)
    assert path.read_text() == CSV
