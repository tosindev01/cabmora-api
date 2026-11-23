"""How instants are written for people to read.

One constant, shared by the use cases and the email templates. It exists
because a clash reported in UTC while the booking grid speaks London time reads
as the app refusing the very slot you just picked — which is exactly what
happened, at 12:00 BST on a call stored as 11:00 UTC.

Storage stays UTC everywhere. This is presentation only, and it lives in
`core` so the application layer can reach it without importing infrastructure.
"""

from zoneinfo import ZoneInfo

#: Cabmora is a UK business; every human-facing time is British local time,
#: which means BST for half the year and an hour of confusion if ignored.
DISPLAY_TZ = ZoneInfo("Europe/London")
