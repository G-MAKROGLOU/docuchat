# Stream contract

- The server-sent event types live in two repos:
  - docuchat-backend: `app/api/schemas/stream.py`
  - docuchat-frontend: `src/lib/stream.ts`
- A change to one file needs the same change to the other file. Merge the two changes together.
- Each event has a `type` field. The `type` value is the discriminator on both sides.
