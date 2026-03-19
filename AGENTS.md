## project context
 - TODO

 ## deployment history
  - a v1 of the app was deployed to an ec2 instance on March 12, 2026

 ## git conventions
 - if asked to build multiple features or fix multiple bugs at once, commit each feature and/or fix separately
 - prepend commit messages with "feat: " for features, "fix: " for bugfixes, "doc: " for readme and other docs changes, "chore: " for gitignore changes, file restructures. For major features, use "feat/feature-name: ". if you're not sure if a feature is "major", ask me. if you're not sure what to prepend with, ask me.
 - when making frontend changes, don't commit, but do draft the commit command and message. I'll want to test the change first
 - when drafting commit commands for me to run, do not concat various commands with `&&` into one long and unreadable command (like `cd` and `git add` and `git commit`). just tell me which dir I should be in, and any other commands should be newline-separated
 - never push to remote or merge to main without explicit approval. assume that I will handle this normally