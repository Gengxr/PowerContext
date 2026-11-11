"""Human-authored reference, NOT a MiniMax generation record."""
def list_tickets(rows, status=None):
    if status is not None and status not in {"open", "closed"}:
        raise ValueError("unsupported status")
    selected = rows if status is None else [row for row in rows if row["status"] == status]
    return [dict(row) for row in sorted(selected, key=lambda row: row["id"])]
