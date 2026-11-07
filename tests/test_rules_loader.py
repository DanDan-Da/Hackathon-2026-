import pymupdf

from app.ingest.rules_loader import load_chunks


def _make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def build(tmp_path):
    (tmp_path / "REG_A" / "sub").mkdir(parents=True)
    (tmp_path / "REG_B").mkdir()
    _make_pdf(tmp_path / "REG_A" / "a.pdf", ["Door width 32 in", "", "Corridor 44 in"])
    (tmp_path / "REG_A" / "sub" / "b.md").write_text("# Heading\nStairs 2", encoding="utf-8")
    (tmp_path / "REG_B" / "c.html").write_text(
        "<html><style>x{}</style><body><p>Ramp slope</p><p>1:12</p></body></html>", encoding="utf-8")
    (tmp_path / "REG_B" / "ignored.png").write_bytes(b"\x89PNG")
    (tmp_path / "stray.txt").write_text("not in a regime", encoding="utf-8")
    return tmp_path


def test_two_regimes_three_files(tmp_path):
    chunks = list(load_chunks(build(tmp_path)))
    assert {c.regime for c in chunks} == {"REG_A", "REG_B"}
    assert {(c.regime, c.document) for c in chunks} == {
        ("REG_A", "a.pdf"), ("REG_A", "sub/b.md"), ("REG_B", "c.html")}

    pdf = [c for c in chunks if c.document == "a.pdf"]
    assert [c.page for c in pdf] == [1, 3]            # blank page 2 skipped, numbering kept
    assert "Door width" in pdf[0].text

    html = next(c for c in chunks if c.document == "c.html")
    assert html.page is None and "Ramp slope" in html.text and "x{}" not in html.text


def test_regime_filter_and_missing_dir(tmp_path):
    root = build(tmp_path)
    assert {c.regime for c in load_chunks(root, regime="REG_B")} == {"REG_B"}
    assert list(load_chunks(tmp_path / "nope")) == []


def test_bad_pdf_is_skipped(tmp_path):
    (tmp_path / "R").mkdir()
    (tmp_path / "R" / "broken.pdf").write_bytes(b"not a pdf")
    (tmp_path / "R" / "ok.txt").write_text("fine", encoding="utf-8")
    assert [c.document for c in load_chunks(tmp_path)] == ["ok.txt"]
