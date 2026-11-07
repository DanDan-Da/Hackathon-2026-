from app.models import Provenance


def test_vector_is_an_accepted_provenance_method():
    p = Provenance(file="ga.pdf", page=1, method="vector", confidence=0.5)
    assert p.method == "vector"
