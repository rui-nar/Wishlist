"""What every claim in the database must satisfy, whatever raced (reserving
plan D2): checked at the end of every concurrency and release test.

The database enforces one claim per gift, its kind, and an occasion for an
unbought claim. The code keeps the rest, checked here:

- an unbought claim has at least one participant;
- a reservation has at most one participant;
- only group gifts' participants pledge;
- a claim's occasion is of its gift's list, the list a hidden gift is for
  included;
- a hidden gift's occasion is of the list it is for (hidden gifts plan D1);
- a claim on a hidden or revealed gift is of no other occasion than the
  gift's (no other occasion sees it, D7);
- every participant of an unbought claim is a giver of its occasion: a
  member of it, or an owner of its list when the list is "for someone else".
"""

from sqlalchemy import Engine, text

VIOLATIONS = {
    "unbought claims with no participant": """
        SELECT c.gift_id FROM gift_claims c
        WHERE c.bought_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM claim_participants p
                          WHERE p.gift_id = c.gift_id)
    """,
    "reservations with more than one participant": """
        SELECT c.gift_id FROM gift_claims c
        JOIN claim_participants p ON p.gift_id = c.gift_id
        WHERE c.kind = 'reservation'
        GROUP BY c.gift_id HAVING count(*) > 1
    """,
    "pledges outside a group gift": """
        SELECT c.gift_id FROM gift_claims c
        JOIN claim_participants p ON p.gift_id = c.gift_id
        WHERE c.kind <> 'group' AND p.pledge_amount IS NOT NULL
    """,
    "claims whose occasion is of another list than their gift": """
        SELECT c.gift_id FROM gift_claims c
        JOIN gifts g ON g.id = c.gift_id
        JOIN occasions o ON o.id = c.occasion_id
        WHERE o.list_id <> coalesce(g.list_id, g.for_list_id)
    """,
    "hidden gifts whose occasion is of another list": """
        SELECT g.id FROM gifts g
        JOIN occasions o ON o.id = g.hidden_occasion_id
        WHERE o.list_id <> g.for_list_id
    """,
    "claims on a hidden gift of another occasion than the gift's": """
        SELECT c.gift_id FROM gift_claims c
        JOIN gifts g ON g.id = c.gift_id
        WHERE g.for_list_id IS NOT NULL
          AND c.occasion_id IS NOT NULL
          AND c.occasion_id IS DISTINCT FROM g.hidden_occasion_id
    """,
    "participants of an unbought claim who are not givers of its occasion": """
        SELECT c.gift_id FROM gift_claims c
        JOIN claim_participants p ON p.gift_id = c.gift_id
        JOIN occasions o ON o.id = c.occasion_id
        JOIN lists l ON l.id = o.list_id
        WHERE c.bought_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM occasion_members m
                          WHERE m.occasion_id = o.id AND m.user_id = p.user_id)
          AND NOT (l.recipient_kind = 'other'
                   AND EXISTS (SELECT 1 FROM list_owners w
                               WHERE w.list_id = l.id AND w.user_id = p.user_id))
    """,
}


def assert_claims_consistent(engine: Engine) -> None:
    with engine.connect() as connection:
        found = {
            name: [str(row[0]) for row in connection.execute(text(query))]
            for name, query in VIOLATIONS.items()
        }
    # One assertion, so a failure shows every broken invariant at once.
    assert found == {name: [] for name in VIOLATIONS}
