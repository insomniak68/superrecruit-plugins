# Narrowfield Plugins

Community and reference plugins for [Narrowfield](https://github.com/insomniak68/narrowfield).

Built on the [Narrowfield SDK](https://github.com/insomniak68/narrowfield-sdk).

## Available Plugins

| Plugin | Type | Description |
|---|---|---|
| `sr-csv` | Source | Import jobs and candidates from CSV files |
| `sr-api` | Source | Fetch candidates and jobs from any REST API |
| `sr-eightfold` | Source | Fetch positions and applicants from Eightfold AI / CareerHub |
| `sr-webhook` | Sink | POST screening decisions to any webhook URL |

## Installation

Each plugin is a standalone Python package:

```bash
# Install a specific plugin
pip install ./plugins/sr-csv
pip install ./plugins/sr-api
pip install ./plugins/sr-eightfold
pip install ./plugins/sr-webhook

# Or install directly from GitHub
pip install "sr-csv @ git+https://github.com/insomniak68/narrowfield-plugins.git#subdirectory=plugins/sr-csv"
pip install "sr-api @ git+https://github.com/insomniak68/narrowfield-plugins.git#subdirectory=plugins/sr-api"
pip install "sr-eightfold @ git+https://github.com/insomniak68/narrowfield-plugins.git#subdirectory=plugins/sr-eightfold"
```

## Usage

Register in Narrowfield's `config/plugins.yaml`:

```yaml
plugins:
  - name: csv
    module: sr_csv
    enabled: true
    config:
      jobs_path: ./data/jobs.csv
      candidates_path: ./data/candidates.csv

  - name: api
    module: sr_api
    enabled: true
    config:
      base_url: https://your-ats.com/api/v1
      auth_type: bearer              # bearer, api_key, basic, or none
      auth_token: "${API_TOKEN}"
      candidates_endpoint: /candidates
      candidates_results_key: data   # dotted path to the array in the JSON response
      candidate_field_map:           # map API fields → CandidateImport fields
        name: full_name
        email: email_address

  - name: eightfold
    module: sr_eightfold
    enabled: true
    config:
      base_url: https://careerhub.microsoft.com
      domain: microsoft.eightfold.ai  # used for profile URLs

      # Cookie auth — no admin access needed (default)
      auth_mode: cookie
      session_cookie: "..."          # DevTools → Application → Cookies → session
      remember_token: "..."          # DevTools → Application → Cookies → remember_token

      # enrich_profiles: true        # fetch full skills & experience per candidate
      # feedback_status: REQUESTED   # REQUESTED or SUBMITTED

      # Alternative: OAuth (requires admin-provisioned credentials)
      # auth_mode: oauth
      # region: us
      # oauth_username: "your-api-user@microsoft.com"
      # oauth_password: "${EIGHTFOLD_API_KEY}"

  - name: webhook
    module: sr_webhook
    enabled: true
    config:
      url: https://your-system.com/api/results
      auth_header: "Bearer ${TOKEN}"
```

Or drop the plugin directory into SR's `plugins/` folder for auto-discovery.

## Writing Your Own Plugin

1. `pip install narrowfield-sdk`
2. Implement `SourcePlugin` and/or `SinkPlugin`
3. See the [Plugin Spec](https://github.com/insomniak68/narrowfield-sdk/blob/main/docs/PLUGIN_SPEC.md) for full reference
4. Submit a PR to add it here!

## License

MIT
