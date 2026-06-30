# SIBYL CLI

Local capture and sync commands for SIBYL project memory.

```bash
pip install -e .
sibyl init --api http://127.0.0.1:8015 --org example-org --project example --repo example-repo
sibyl add --type implementation_note --title "Useful context" --summary "A concise durable note."
sibyl summary --text "End-of-day project summary."
sibyl sync
```

Store access tokens in `SIBYL_API_KEY` or `.sibyl/secrets.json`; never commit secrets.
