from agent.sql_guard import UnsafeSQLError, extract_sql, validate_sql


def _blocked(sql: str) -> bool:
    try:
        validate_sql(sql)
        return False
    except UnsafeSQLError:
        return True


def test_select_gets_limit():
    assert validate_sql("SELECT * FROM partners").endswith("LIMIT 200")


def test_existing_limit_kept():
    out = validate_sql("SELECT * FROM partners LIMIT 5;")
    assert out == "SELECT * FROM partners LIMIT 5"
    assert validate_sql("SELECT * FROM partners LIMIT 5 OFFSET 10").count("LIMIT") == 1


def test_cte_allowed():
    assert not _blocked("WITH x AS (SELECT 1 AS a) SELECT a FROM x")


def test_write_and_multi_statement_blocked():
    for sql in ["DELETE FROM partners", "DROP TABLE partners", "UPDATE partners SET hub='x'",
                "SELECT 1; DROP TABLE partners", "PRAGMA table_info(partners)",
                "ATTACH DATABASE 'x.db' AS x", "WITH x AS (SELECT 1) DELETE FROM partners", ""]:
        assert _blocked(sql), sql


def test_keywords_inside_strings_are_fine():
    assert not _blocked("SELECT * FROM ireg_tests WHERE failure_cause = 'Update Location Reject'")
    assert not _blocked("SELECT 'a;b' AS x")


def test_extract_sql_from_fenced_reply():
    reply = "Here you go:\n```sql\nSELECT tadig FROM partners;\n```\nThis lists partners."
    assert extract_sql(reply) == "SELECT tadig FROM partners"


def test_extract_sql_without_fence():
    assert extract_sql("Sure! SELECT 1") == "SELECT 1"
