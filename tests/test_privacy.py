from backend.privacy import contains_sensitive_text, project_label, redact_text


def test_project_label_does_not_expose_full_path() -> None:
    label, hashed = project_label(r"C:\Users\Example\Projects\demo-app")
    assert "C:\\Users" not in label
    assert "Example" not in label
    assert label.startswith("demo-app#")
    assert hashed


def test_redacts_secret_like_text() -> None:
    text = "OPENAI_API_KEY=sk-thisisnotarealkeybutlookslong"
    assert contains_sensitive_text(text)
    assert "sk-" not in redact_text(text)
