# Narrowfield Plugins

Community and reference plugins for [Narrowfield](https://github.com/insomniak68/narrowfield).

Built on the [Narrowfield SDK](https://github.com/insomniak68/narrowfield-sdk).

## Available Plugins

| Plugin | Type | Description |
|---|---|---|
| `sr-csv` | Source | Import jobs and candidates from CSV files |
| `sr-webhook` | Sink | POST screening decisions to any webhook URL |

## Installation

Each plugin is a standalone Python package:

```bash
# Install a specific plugin
pip install ./plugins/sr-csv
pip install ./plugins/sr-webhook

# Or install directly from GitHub
pip install "sr-csv @ git+https://github.com/insomniak68/narrowfield-plugins.git#subdirectory=plugins/sr-csv"
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
