"""Eval cases for the ibkr-data-protection skill.

Scoped narrowly to the account-id category for now: one planted leak we
expect the model to flag, one properly anonymized sample it must leave alone.
"""

TEST_CASES = [
    {
        "name": "account_id_leak",
        "input": (
            "# Sample IBKR account snippet\n"
            "account_id: U8675309\n"
            "currency: USD\n"
        ),
        "should_flag": True,
        "expected_categories": ["account-id"],
    },
    {
        "name": "account_id_clean_placeholder",
        "input": (
            "# Sample IBKR account snippet\n"
            "account_id: U1234567\n"
            "currency: USD\n"
        ),
        "should_flag": False,
        "expected_categories": [],
    },
]
