# STRATA CLI

Local capture and sync commands for STRATA project memory.

```bash
pip install -e .
strata init --api http://127.0.0.1:8015 --org example-org --project example --repo example-repo
strata add --type implementation_note --title "Useful context" --summary "A concise durable note."
strata summary --text "End-of-day project summary."
strata sync
```

Store access tokens in `STRATA_API_KEY` or `.strata/secrets.json`; never commit secrets.
