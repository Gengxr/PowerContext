"""Small in-memory ticket query service; initial version lacks status filtering."""
def list_tickets(rows, status=None):
    return [dict(row) for row in sorted(rows, key=lambda row: row["id"])]
