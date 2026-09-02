from lcat.loaders import CodeDoc, MarkdownDoc, TableDoc, load


def test_markdown_roundtrip():
    doc = load("# hi\n", "md")
    assert isinstance(doc, MarkdownDoc)
    assert doc.text == "# hi\n"


def test_csv_header_and_shape():
    doc = load("a,b\n1,2\n3,4\n", "csv")
    assert isinstance(doc, TableDoc)
    assert doc.columns == ["a", "b"]
    assert doc.rows == [["1", "2"], ["3", "4"]]
    assert doc.shape == (2, 2)


def test_csv_ragged_rows_are_padded():
    doc = load("a,b,c\n1,2\n3,4,5\n", "csv")
    assert doc.rows == [["1", "2", ""], ["3", "4", "5"]]


def test_csv_no_header_synthesises_columns():
    doc = load("1,2\n3,4\n", "csv", has_header=False)
    assert doc.columns == ["col1", "col2"]
    assert len(doc.rows) == 2


def test_csv_blank_header_cells_get_names():
    doc = load("a,,c\n1,2,3\n", "csv")
    assert doc.columns == ["a", "col2", "c"]


def test_tsv_uses_tab_by_default():
    doc = load("a\tb\n1\t2\n", "tsv")
    assert doc.columns == ["a", "b"]


def test_json_records_union_keys_in_order():
    doc = load('[{"a": 1}, {"b": 2, "a": 3}]', "json")
    assert doc.columns == ["a", "b"]
    assert doc.rows == [["1", ""], ["3", "2"]]


def test_json_nested_values_are_compacted():
    doc = load('[{"tags": ["x", "y"], "meta": {"k": 1}}]', "json")
    assert doc.rows == [['["x","y"]', '{"k":1}']]


def test_json_lines():
    doc = load('{"a": 1}\n{"a": 2}\n', "json")
    assert doc.columns == ["a"]
    assert doc.rows == [["1"], ["2"]]


def test_json_object_becomes_key_value_table():
    doc = load('{"a": 1, "b": "two"}', "json")
    assert doc.columns == ["key", "value"]
    assert doc.rows == [["a", "1"], ["b", "two"]]


def test_json_scalar_list():
    doc = load("[1, 2, 3]", "json")
    assert doc.columns == ["value"]
    assert doc.rows == [["1"], ["2"], ["3"]]


def test_non_tabular_json_falls_back_to_code():
    doc = load('[[1, 2], {"a": 1}]', "json")
    assert isinstance(doc, CodeDoc)
    assert doc.lexer == "json"


def test_broken_json_is_shown_as_code():
    doc = load("{not json at all", "json")
    assert isinstance(doc, CodeDoc)


def test_booleans_and_nulls():
    doc = load('[{"ok": true, "missing": null}]', "json")
    assert doc.rows == [["true", ""]]
