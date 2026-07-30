from copilot.config import Settings


def test_database_url_can_be_built_from_secret_components() -> None:
    settings = Settings(
        environment="production",
        auth_mode="bearer",
        api_key="test-only-secret",
        database_host="db.internal",
        database_user="copilot@example",
        database_password="unsafe/test:value",
    )

    assert settings.resolved_database_url == (
        "postgresql+asyncpg://copilot%40example:unsafe%2Ftest%3Avalue@db.internal:5432/copilot"
    )
