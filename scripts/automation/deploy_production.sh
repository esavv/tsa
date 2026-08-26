#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SSH_BIN="${SSH_BIN:-/usr/bin/ssh}"
GIT_BIN="${GIT_BIN:-/usr/bin/git}"
EC2_HOST="${EC2_HOST:-tsa-times.com}"
EC2_USER="${EC2_USER:-ubuntu}"
default_ec2_key="$REPO_DIR/aws_ec2.pem"
if [[ ! -r "$default_ec2_key" ]]; then
    default_ec2_key="$HOME/Projects/tsa/aws_ec2.pem"
fi
EC2_KEY="${EC2_KEY:-$default_ec2_key}"

usage() {
    printf 'Usage: %s COMMIT AIRPORT [AIRPORT ...]\n' "$0" >&2
    exit 2
}

[[ $# -ge 2 ]] || usage
target_commit="$1"
shift
[[ "$target_commit" =~ ^[0-9a-f]{40}$ ]] || usage
for airport in "$@"; do
    [[ "$airport" =~ ^[A-Z0-9]{3}$ ]] || usage
done
[[ -r "$EC2_KEY" ]] || { printf 'EC2 key is unavailable: %s\n' "$EC2_KEY" >&2; exit 1; }

cd "$REPO_DIR"
remote_main="$($GIT_BIN ls-remote origin refs/heads/main | /usr/bin/cut -f1)"
[[ "$remote_main" == "$target_commit" ]] || {
    printf 'Target %s is not current origin/main (%s).\n' "$target_commit" "$remote_main" >&2
    exit 1
}

"$SSH_BIN" \
    -i "$EC2_KEY" \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    "$EC2_USER@$EC2_HOST" \
    /bin/bash -s -- "$target_commit" "$@" <<'REMOTE'
set -euo pipefail

target_commit="$1"
shift
repo_dir="/home/ubuntu/tsa"
wait_deadline=$(( $(date +%s) + 1800 ))

cd "$repo_dir"

if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'Production worktree is dirty; refusing deployment.\n' >&2
    git status --short >&2
    exit 1
fi

git fetch origin main
[[ "$(git rev-parse origin/main)" == "$target_commit" ]] || {
    printf 'Production fetched a different origin/main commit.\n' >&2
    exit 1
}
current_commit="$(git rev-parse HEAD)"
git merge-base --is-ancestor "$current_commit" "$target_commit" || {
    printf 'Production cannot fast-forward from %s to %s.\n' "$current_commit" "$target_commit" >&2
    exit 1
}

requirements_changed=false
if ! git diff --quiet "$current_commit" "$target_commit" -- requirements.txt; then
    requirements_changed=true
fi
webapp_changed=false
while IFS= read -r changed_path; do
    case "$changed_path" in
        app.py|templates/*|static/*) webapp_changed=true ;;
    esac
done < <(git diff --name-only "$current_commit" "$target_commit")

while true; do
    minute="$(date -u +%M)"
    minute=$((10#$minute))
    remainder=$((minute % 15))
    scrape_active=false
    if pgrep -f '[s]cripts/run_scrape.py' >/dev/null; then
        scrape_active=true
    fi
    if [[ "$remainder" -ge 3 && "$remainder" -le 5 && "$scrape_active" == false ]]; then
        break
    fi
    if [[ "$(date +%s)" -ge "$wait_deadline" ]]; then
        printf 'No safe deployment window became available within 30 minutes.\n' >&2
        exit 1
    fi
    printf 'Waiting for a safe deployment window; UTC minute=%02d scrape_active=%s\n' \
        "$minute" "$scrape_active"
    sleep 20
done

git merge --ff-only "$target_commit"
if [[ "$requirements_changed" == true ]]; then
    ./venv/bin/pip install -r requirements.txt
fi

set -a
. ./.env
set +a
for airport in "$@"; do
    ./venv/bin/python scripts/scraper.py --preview "$airport"
done

if [[ "$webapp_changed" == true ]]; then
    sudo systemctl restart tsa-webapp
    sudo systemctl is-active --quiet tsa-webapp
fi

printf 'DEPLOYED_COMMIT=%s\n' "$(git rev-parse HEAD)"
printf 'DEPLOYED_AT_UTC=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REMOTE
