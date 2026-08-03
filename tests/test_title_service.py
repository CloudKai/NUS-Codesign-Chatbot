from backend.title_service import NotebookTitleService


def test_notebook_title_service_shortens_the_older_adult_crossing_topic():
    assert NotebookTitleService.generate(
        "Helping elderly people cross the road safely without struggling or danger."
    ) == "Elderly Road Safety"


def test_notebook_title_service_keeps_five_meaningful_words_at_most():
    title = NotebookTitleService.generate(
        "I want to compare renewable energy storage policies across several cities."
    )

    assert title == "Compare Renewable Energy Storage Policies"
    assert len(title.split()) <= 5


def test_legacy_first_prompt_title_is_upgraded_without_touching_custom_titles():
    prompt = "Understand their pain and struggle and finding ways for them to walk safely"
    current_title = prompt[:70]
    replacement = NotebookTitleService.replacement_for_legacy_title(
        current_title,
        [prompt, "Helping elderly people cross the road safely."],
    )

    assert replacement == "Elderly Road Safety"
    assert NotebookTitleService.replacement_for_legacy_title(
        "My deliberately detailed research title",
        [prompt],
    ) is None
