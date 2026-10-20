# Privacy

eval-conductor collects nothing.

- All commands run local Python scripts inside your own repository.
- No command makes a network call, with one opt-in exception: `/conductor
  --verify-evidence` sends one anonymous GET to `api.github.com` for the CI run
  URL you cite. No credential and none of your files are sent.
- No telemetry, no analytics, no accounts, no data leaves your machine.
- Files the plugin creates (registry, baseline, candidate, ledger) live in
  your repo, under your version control, owned by you.

The only network activity ever involved is what YOU wire up yourself
(e.g. your own GitHub Actions running the gate in your CI).

Questions: open an issue at
https://github.com/Rmasood1122/eval-conductor/issues
