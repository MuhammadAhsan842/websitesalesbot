# Recover documents missing from a Zoho Deal

Run this on the machine where the bot stored the original uploads, using the same
Python environment and `data/ayyan.db` as the server. Stop that server before
running recovery so it cannot send the same queue concurrently. Update the branch
without discarding local changes, and restart the server afterward.

The older queue serializer could mark a document event `synced` after updating
Deal fields. That Deal ID is not an attachment receipt. Commit `a182a96` fixes new
delivery; recovery repairs historical uploads without asking drivers to select
their stored files again.

## Inspect a local recovery plan

From the repository root:

```bash
python -m app.recover_document_handoff \
  --inquiry opp_1794492813653_46279a \
  --deal-id 7652608000001110002
```

Without `--send`, this only lists the accepted local originals for this inquiry.
It does not contact Zoho or send documents. Verify the inquiry and Deal against
the record being reviewed.

## Send and confirm

```bash
python -m app.recover_document_handoff \
  --inquiry opp_1794492813653_46279a \
  --deal-id 7652608000001110002 \
  --send
```

The command uses the existing server-side Zoho connection; do not paste tokens.
It checks the Deal mapping, queues every accepted original associated with this
case, and publishes the current stored review report as a related Note. It does
not rerun OCR/model review or approve the documents. Originals whose review never
completed are included.

Historical malformed success records and offline-only delivery records are
replayed. Existing confirmed attachments are retained. When a filename matches
an existing remote attachment, recovery compares the downloaded original bytes
before adopting that receipt, so a lost response need not create a duplicate.

Recovery reads the Deal's Attachments and Notes lists after submission. It prints
the filename, actual attachment ID, confirmation result and any saved delivery
error. `verified: true` means the selected originals and current report IDs were
found on this Deal. It is not onboarding approval or task-assignment verification.

Refresh **Deals → the selected Deal → Attachments** to open the originals, and
**Notes** to read the report. If the command reports a failed request, disconnected
account, mismatched mapping, or missing local file, resolve that specific issue;
do not treat a receipt in the chat as proof of remote delivery.

The command is scoped to the requested inquiry. It does not send or expire other
inquiries' queued operations. Its remote file/note read-back tests use mocked Zoho
responses; successful delivery to an operator's live account must be established
by running it there.
