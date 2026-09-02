from pathlib import Path

from lcat.detect import mode_from_extension, resolve_mode, sniff_delimiter, sniff_mode


def test_extension_mapping():
    assert mode_from_extension(Path("a.md")) == "md"
    assert mode_from_extension(Path("a.MARKDOWN")) == "md"
    assert mode_from_extension(Path("a.csv")) == "csv"
    assert mode_from_extension(Path("a.tsv")) == "tsv"
    assert mode_from_extension(Path("a.jsonl")) == "json"
    assert mode_from_extension(Path("a.rst")) is None


def test_explicit_mode_wins_over_extension():
    assert resolve_mode(Path("a.md"), "csv", "x,y\n1,2\n") == "csv"


def test_sniff_json_and_jsonl():
    assert sniff_mode('[{"a": 1}]') == "json"
    assert sniff_mode('{"a": 1}\n{"a": 2}\n') == "json"


def test_sniff_delimited():
    assert sniff_mode("a,b,c\n1,2,3\n4,5,6\n") == "csv"
    assert sniff_mode("a\tb\tc\n1\t2\t3\n4\t5\t6\n") == "tsv"


def test_sniff_falls_back_to_markdown():
    assert sniff_mode("# Title\n\nSome prose that is not a table.\n") == "md"
    assert sniff_mode("") == "md"


def test_resolve_uses_sniffing_without_extension():
    assert resolve_mode(Path("data"), "auto", "a;b\n1;2\n3;4\n") == "csv"
    assert resolve_mode(None, "auto", '[{"a": 1}]') == "json"


def test_sniff_delimiter():
    assert sniff_delimiter("a;b\n1;2\n3;4\n") == ";"
    assert sniff_delimiter("just one line") == ","


def test_sniff_handles_quoted_delimiters():
    sample = 'id,note\n1,"a, b, c"\n2,"d, e"\n'
    assert sniff_mode(sample) == "csv"


def test_markdown_prose_is_not_mistaken_for_a_table():
    prose = "Some prose.\n\nMore prose here, with a comma.\n\nAnd a third line.\n"
    assert sniff_mode(prose) == "md"


def test_sniff_real_csv_that_defeats_csv_sniffer():
    sample = (
        "id,name,note\n"
        '1,Ada,"Wrote the first algorithm, intended for a machine, long note"\n'
        '2,Grace,Coined "debugging"\n'
        "3,Alan,\n"
    )
    assert sniff_mode(sample) == "csv"
    assert sniff_delimiter(sample) == ","


def test_pipe_delimited():
    assert sniff_mode("a|b|c\n1|2|3\n") == "csv"
    assert sniff_delimiter("a|b|c\n1|2|3\n") == "|"


def test_markdown_pipe_table_is_markdown():
    assert sniff_mode("| a | b |\n| - | - |\n| 1 | 2 |\n") == "md"
    assert sniff_mode("a | b\n--|--\n1 | 2\n") == "md"
