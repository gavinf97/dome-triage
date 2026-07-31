from dome_triage.keywords.curated_terms import ADDED_NEGATIVE_TERMS, ADDED_POSITIVE_TERMS


def test_no_internal_duplicates_within_positive_terms():
    terms = [entry["term"] for entry in ADDED_POSITIVE_TERMS]
    assert len(terms) == len(set(terms))


def test_no_internal_duplicates_within_negative_terms():
    terms = [entry["term"] for entry in ADDED_NEGATIVE_TERMS]
    assert len(terms) == len(set(terms))


def test_no_term_appears_in_both_positive_and_negative():
    positive_terms = {entry["term"] for entry in ADDED_POSITIVE_TERMS}
    negative_terms = {entry["term"] for entry in ADDED_NEGATIVE_TERMS}
    assert positive_terms.isdisjoint(negative_terms)


def test_every_entry_has_a_term_and_category():
    for entry in ADDED_POSITIVE_TERMS + ADDED_NEGATIVE_TERMS:
        assert entry.get("term"), entry
        assert entry.get("category"), entry


def test_terms_are_lowercase_matching_candidate_file_convention():
    for entry in ADDED_POSITIVE_TERMS + ADDED_NEGATIVE_TERMS:
        assert entry["term"] == entry["term"].lower(), entry["term"]
