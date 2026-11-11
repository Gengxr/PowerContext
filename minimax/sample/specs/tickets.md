# Ticket query specification v1
## SDD-001: filtering
list_tickets(rows, status=None) accepts None, "open" or "closed".
None returns all tickets. A specified status returns only exact matches.
## SDD-002: invalid input
Any other status (including empty string, uppercase, integers) raises ValueError.
## SDD-003: compatibility
Results are ordered by ascending numeric id. Preserve every field.
Do not mutate the input list or dictionaries. Return independent dictionary copies.
An empty input returns [] for valid statuses, but still rejects invalid status.
