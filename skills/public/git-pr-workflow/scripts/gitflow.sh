#!/usr/bin/env bash
# gitflow.sh -- reliable git and pull-request primitives for DeerFlow agents.
#
#   bash gitflow.sh <command> [options]      (bash gitflow.sh --help lists them)
#
# Every command prints one JSON object on stdout ("ok": true or false). A
# refusal or failure also writes "gitflow <command>: error: ..." and a hint on
# stderr and exits 1; a usage error exits 2 without JSON. Output is redacted:
# credentials in URLs and the values of the GitHub token variables never show.
#
# This script is the one place in the skill that starts processes: git, gh
# (when installed), and the python3 helpers next to it. gitflow_json.py and
# gitflow_scan.py only parse and format; gitflow_github.py calls the GitHub
# REST API over HTTPS. Requires bash 4.4+, git and python3 3.10+.

set -Eeuo pipefail

if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
    printf 'gitflow: bash 4.4 or newer is required (found %s)\n' "$BASH_VERSION" >&2
    exit 2
fi

_src="${BASH_SOURCE[0]}"
if [[ $_src == */* ]]; then HERE="$(cd -- "${_src%/*}" && pwd)"; else HERE="$(pwd)"; fi
PY=python3
CHECKPOINT_NS="refs/deerflow-checkpoints/"
CK_FORMAT='%(refname:lstrip=2)%00%(objectname)%00%(creatordate:iso-strict)%00%(contents:subject)%00%(contents:body)%00'
WORKTREE_DIR=".worktrees"
WORKTREE_PREFIX="agent/"
PUSH_ATTEMPTS=5 # the first try plus up to 4 retries
RETRY_BASE=2    # seconds; waits are 2, 4, 8, 16
NET_TIMEOUT=300
TIMEOUT_BIN="$(type -P timeout || true)"
LOCK_RE="unable to create '[^']*\\.lock'|cannot lock ref|index\\.lock|another git process seems to be running"
PERMANENT_RE='authentication failed|permission denied|could not read username|returned error: 4[0-9][0-9]|repository not found|\[rejected\]|remote rejected|non-fast-forward|protected branch|stale info'
TRANSIENT_RE='could not resolve host|temporary failure in name resolution|name or service not known|connection (timed out|reset|refused|closed)|operation timed out|timed out|early eof|rpc failed|remote end hung up unexpectedly|failed to connect|network is unreachable|unexpected disconnect|broken pipe|ssl_|gnutls|tls connection|returned error: 5[0-9][0-9]|http 5[0-9][0-9]|internal server error|bad gateway|service unavailable|gateway time-?out'

export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never GIT_EDITOR=true GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 PYTHONDONTWRITEBYTECODE=1
# Paths given to --paths are file names: brackets, stars and question marks are
# literal characters, never glob patterns.
export GIT_LITERAL_PATHSPECS=1

CMD=""
REPO=""
REPO_ARG=""
REMOTE="origin"
SAVED_INDEX=""        # backup copy of the index file while a commit is staged
SAVED_INDEX_TARGET="" # the index file that the backup belongs to
GIT_INDEX_OVERRIDE=""
GIT_STDIN=""
GIT_NET=0
GOUT=""
GERR=""
GRC=0
CLEANUP=()

usage() {
    cat <<'EOF'
gitflow.sh - reliable git and pull-request primitives; one JSON object on stdout

  preflight [--remote R]
  branch NAME [--from REF] [--remote R]
  checkpoint [-m MSG]
  checkpoints [--limit N]
  restore ID|latest [--paths P ...] [--clean]
  commit (-m MSG ... | --message-file FILE|-) [--paths P ... | --all] [--allow-default-branch]
  push [--remote R] [--force-with-lease]
  pr create --title T (--body B | --body-file FILE|-) [--base B] [--draft] [--remote R]
  pr status [--number N] [--remote R]
  worktree add NAME [--from REF] [--remote R]
  worktree remove NAME [--force] [--delete-branch]
  worktree list

Every command accepts --repo DIR (default: the current directory).
Paths given to --paths are relative to the repository root.
EOF
}

usage_error() {
    printf 'gitflow%s: usage error: %s\n' "${CMD:+ $CMD}" "$1" >&2
    printf 'Run: bash gitflow.sh --help\n' >&2
    exit 2
}

if ! type -P "$PY" >/dev/null; then
    printf '{"ok": false, "error": "python3 is required by gitflow.sh"}\n'
    printf 'gitflow: error: python3 is required by gitflow.sh\n' >&2
    exit 1
fi

if ! TMP="$(mktemp -d "${TMPDIR:-/tmp}/gitflow.XXXXXXXX" 2>/dev/null)"; then
    printf '{"ok": false, "error": "cannot create a temporary directory; check that TMPDIR names a writable directory"}\n'
    printf 'gitflow: error: cannot create a temporary directory; check that TMPDIR names a writable directory\n' >&2
    exit 1
fi
OUT="$TMP/out.rec"
ERR="$TMP/err.rec"
: >"$OUT"
: >"$ERR"

cleanup() { # never changes the exit status
    trap - ERR
    local file
    for file in "${CLEANUP[@]}"; do
        rm -f -- "$file" "$file.lock" || true
    done
    if [[ -n ${TMP-} && -d $TMP && $TMP == */gitflow.* ]]; then
        rm -f -- "$TMP"/* || true
        rmdir -- "$TMP" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ------------------------------------------------------------------ output
# Records are NUL-terminated (type, key, value) triples; gitflow_json.py turns
# them into the JSON object (see its docstring for the record types).

_rec() { printf '%s\0%s\0%s\0' "$2" "$3" "$4" >>"$1"; }
put() { _rec "$OUT" s "$1" "$2"; }
put_num() { _rec "$OUT" n "$1" "${2-}"; }
put_bool() { _rec "$OUT" b "$1" "$2"; }
put_null() { _rec "$OUT" z "$1" ""; }
put_list() { _rec "$OUT" A "$1" ""; }
add() { _rec "$OUT" a "$1" "$2"; }
warn() { _rec "$OUT" a warnings "$1"; }
put_opt() { if [[ -n ${2-} ]]; then put "$1" "$2"; else put_null "$1"; fi; }
bool() { if "$@"; then printf true; else printf false; fi; }

add_file_z() { # add_file_z KEY FILE: every NUL-separated entry of FILE into the list KEY
    local key="$1" item
    put_list "$key"
    while IFS= read -r -d '' item; do
        if [[ -n $item ]]; then add "$key" "$item"; fi
    done <"$2"
}

finish() {
    trap - ERR
    "$PY" "$HERE/gitflow_json.py" emit --ok --command "$CMD" <"$OUT"
    exit 0
}

backup_index() { # copy the index file itself, so flags and intent-to-add entries survive a refusal
    g rev-parse --git-path index
    SAVED_INDEX_TARGET="$GOUT"
    if [[ $SAVED_INDEX_TARGET != /* ]]; then SAVED_INDEX_TARGET="$REPO/$SAVED_INDEX_TARGET"; fi
    SAVED_INDEX="$TMP/index.backup"
    if [[ -f $SAVED_INDEX_TARGET ]]; then
        cp -p -- "$SAVED_INDEX_TARGET" "$SAVED_INDEX"
    else
        SAVED_INDEX="absent" # a repository without an index file yet
    fi
}

restore_saved_index() {
    if [[ -n $SAVED_INDEX ]]; then
        local saved="$SAVED_INDEX"
        SAVED_INDEX=""
        if [[ $saved == absent ]]; then
            rm -f -- "$SAVED_INDEX_TARGET" || true
        else
            # Copy next to the index, then rename over it: the swap is atomic.
            cp -p -- "$saved" "$SAVED_INDEX_TARGET.gitflow" && mv -f -- "$SAVED_INDEX_TARGET.gitflow" "$SAVED_INDEX_TARGET" || true
        fi
        _rec "$ERR" b index_restored true
    fi
}

_emit_fail() {
    restore_saved_index
    "$PY" "$HERE/gitflow_json.py" emit --fail --command "$CMD" <"$ERR" || printf '{"ok": false, "error": "gitflow could not format its error"}\n'
    exit 1
}

die() { # die MESSAGE [HINT]
    trap - ERR
    _rec "$ERR" s error "$1"
    if [[ -n ${2-} ]]; then _rec "$ERR" s hint "$2"; fi
    _emit_fail
}

git_die() { # git_die LABEL [FALLBACK_HINT]: report the last failed git call
    trap - ERR
    _rec "$ERR" s git_subcommand "$1"
    _rec "$ERR" s stderr "$GERR"
    if [[ -n ${2-} ]]; then _rec "$ERR" s fallback_hint "$2"; fi
    _emit_fail
}

on_error() {
    local status=$? line="$1"
    trap - ERR
    if ((BASH_SUBSHELL > 0)); then exit "$status"; fi
    die "internal error: a command failed at gitflow.sh line $line (exit status $status)" "The operation may be incomplete; check the state with preflight before retrying."
}
trap 'on_error $LINENO' ERR

# --------------------------------------------------------------------- git

_git_exec() { # _git_exec OUTFILE DIR ARGS...: sets GRC and GERR; retries lock contention
    local outfile="$1" dir="$2" attempt=1
    shift 2
    local -a pre=()
    if ((GIT_NET)) && [[ -n $TIMEOUT_BIN ]]; then pre=("$TIMEOUT_BIN" "$NET_TIMEOUT"); fi
    while :; do
        GRC=0
        if [[ -n $GIT_INDEX_OVERRIDE ]]; then
            LC_ALL=C GIT_INDEX_FILE="$GIT_INDEX_OVERRIDE" "${pre[@]}" git -C "$dir" "$@" <"${GIT_STDIN:-/dev/null}" >"$outfile" 2>"$TMP/git.err" || GRC=$?
        else
            LC_ALL=C "${pre[@]}" git -C "$dir" "$@" <"${GIT_STDIN:-/dev/null}" >"$outfile" 2>"$TMP/git.err" || GRC=$?
        fi
        GERR="$(<"$TMP/git.err")"
        if ((GRC == 124)) && ((${#pre[@]})); then GERR+=$'\n'"git $1: operation timed out after ${NET_TIMEOUT}s"; fi
        if ((GRC != 0 && attempt < 4)) && [[ ${GERR,,} =~ $LOCK_RE ]]; then
            sleep "$attempt"
            attempt=$((attempt + 1))
            continue
        fi
        return 0
    done
}

gx() { # run git in $REPO; never fails; GOUT holds stdout without trailing newlines
    _git_exec "$TMP/git.out" "$REPO" "$@"
    GOUT="$(<"$TMP/git.out")"
}

_label() { # the git subcommand among ARGS, skipping -c/-C options
    while (($#)); do
        case "$1" in
        -c | -C) shift 2 ;;
        -*) shift ;;
        *)
            printf '%s' "$1"
            return 0
            ;;
        esac
    done
    printf git
}

g() { # run git in $REPO; on failure report it and exit
    gx "$@"
    if ((GRC != 0)); then git_die "$(_label "$@")"; fi
}

g_file() { # g_file FILE ARGS...: like g, stdout (possibly NUL-separated) into FILE
    local file="$1"
    shift
    _git_exec "$file" "$REPO" "$@"
    if ((GRC != 0)); then git_die "$(_label "$@")"; fi
}

is_transient() {
    local text="${1,,}"
    if [[ $text =~ $PERMANENT_RE ]]; then return 1; fi
    [[ $text =~ $TRANSIENT_RE ]]
}

git_net() { # git_net MAX_ATTEMPTS ARGS...: a networked git call with retries; sets ATTEMPTS DELAYS
    local max="$1" attempt=1 delay
    shift
    DELAYS=()
    while :; do
        GIT_NET=1
        _git_exec "$TMP/net.out" "$REPO" "$@"
        GIT_NET=0
        GOUT="$(<"$TMP/net.out")"
        ATTEMPTS=$attempt
        if ((GRC == 0 || attempt >= max)) || ! is_transient "$GERR"; then return 0; fi
        delay=$((RETRY_BASE * (1 << (attempt - 1))))
        DELAYS+=("$delay")
        sleep "$delay"
        attempt=$((attempt + 1))
    done
}

last_error_line() {
    local line out=""
    while IFS= read -r line; do
        if [[ -n ${line//[[:space:]]/} && $line != hint:* ]]; then out="$line"; fi
    done <<<"$1"
    printf '%s' "$out"
}

resolve_repo() {
    local start="${REPO_ARG:-$PWD}"
    if [[ ! -d $start ]]; then die "$start is not a directory" "Pass --repo with the path of the repository checkout."; fi
    _git_exec "$TMP/git.out" "$start" rev-parse --show-toplevel
    if ((GRC != 0)); then
        _rec "$ERR" s stderr "$GERR"
        _rec "$ERR" s fallback_hint "cd into the repository (for a clone, /mnt/user-data/workspace/<repo>) or pass --repo DIR."
        die "$start is not inside a git work tree: $(last_error_line "$GERR")"
    fi
    REPO="$(<"$TMP/git.out")"
}

rev() { # rev REF -> REV (commit sha, or empty)
    gx rev-parse --verify --quiet "$1^{commit}"
    if ((GRC == 0)) && [[ -n $GOUT ]]; then REV="$GOUT"; else REV=""; fi
}

ref_exists() {
    gx show-ref --verify --quiet "$1"
    ((GRC == 0))
}

current_branch() { # -> BRANCH (empty when detached)
    gx symbolic-ref --quiet --short HEAD
    if ((GRC == 0)); then BRANCH="$GOUT"; else BRANCH=""; fi
}

has_remote() {
    local name
    gx remote
    while IFS= read -r name; do
        if [[ $name == "$1" ]]; then return 0; fi
    done <<<"$GOUT"
    return 1
}

default_branch() { # -> DEFAULT_BRANCH DEFAULT_SOURCE
    local candidate prefix="refs/remotes/$REMOTE/"
    gx symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD"
    if ((GRC == 0)) && [[ $GOUT == "$prefix"* ]]; then
        DEFAULT_BRANCH="${GOUT#"$prefix"}"
        DEFAULT_SOURCE="$REMOTE/HEAD"
        return 0
    fi
    for candidate in main master; do
        if ref_exists "refs/remotes/$REMOTE/$candidate"; then
            DEFAULT_BRANCH="$candidate"
            DEFAULT_SOURCE="$REMOTE/$candidate"
            return 0
        fi
    done
    for candidate in main master; do
        if ref_exists "refs/heads/$candidate"; then
            DEFAULT_BRANCH="$candidate"
            DEFAULT_SOURCE="local branch"
            return 0
        fi
    done
    rev HEAD
    if [[ -z $REV ]]; then
        current_branch
        if [[ -n $BRANCH ]]; then
            DEFAULT_BRANCH="$BRANCH"
            DEFAULT_SOURCE="unborn HEAD"
            return 0
        fi
    fi
    gx config --get init.defaultBranch
    if ((GRC == 0)) && [[ -n $GOUT ]]; then
        DEFAULT_BRANCH="$GOUT"
        DEFAULT_SOURCE="init.defaultBranch"
        return 0
    fi
    DEFAULT_BRANCH="main"
    DEFAULT_SOURCE="fallback"
}

default_branch_net() { # default_branch, but asks the remote when its HEAD is not recorded locally
    local line re='^ref: refs/heads/([^[:space:]]+)[[:space:]]+HEAD$'
    DEFAULT_UNKNOWN=false
    default_branch
    if [[ $DEFAULT_SOURCE == "$REMOTE/HEAD" ]] || ! has_remote "$REMOTE"; then return 0; fi
    # A clone made with git init + fetch (as CI checkouts are) has no
    # origin/HEAD; guessing main would leave the real default unprotected.
    git_net 2 ls-remote --symref "$REMOTE" HEAD
    if ((GRC == 0)); then
        while IFS= read -r line; do
            if [[ $line =~ $re ]]; then
                DEFAULT_BRANCH="${BASH_REMATCH[1]}"
                DEFAULT_SOURCE="$REMOTE HEAD (ls-remote)"
                return 0
            fi
        done <<<"$GOUT"
    fi
    DEFAULT_UNKNOWN=true
}

warn_default_unknown() {
    if [[ ${DEFAULT_UNKNOWN-false} == true ]]; then
        warn "could not ask $REMOTE for its default branch; assuming '$DEFAULT_BRANCH' ($DEFAULT_SOURCE), and main and master stay protected"
    fi
}

is_protected() { [[ $1 == "$DEFAULT_BRANCH" || $1 == main || $1 == master ]]; }

operation_in_progress() { # -> OPERATION
    g rev-parse --absolute-git-dir
    local gd="$GOUT"
    OPERATION=""
    if [[ -e $gd/rebase-merge || -e $gd/rebase-apply ]]; then
        OPERATION=rebase
    elif [[ -e $gd/MERGE_HEAD ]]; then
        OPERATION=merge
    elif [[ -e $gd/CHERRY_PICK_HEAD ]]; then
        OPERATION=cherry-pick
    elif [[ -e $gd/REVERT_HEAD ]]; then
        OPERATION=revert
    elif [[ -e $gd/BISECT_LOG ]]; then
        OPERATION=bisect
    fi
}

common_dir() { # -> COMMON (absolute, symlinks resolved)
    g rev-parse --git-common-dir
    local dir="$GOUT"
    if [[ $dir != /* ]]; then dir="$REPO/$dir"; fi
    COMMON="$(cd -- "$dir" && pwd -P)"
}

url_has_credentials() {
    local re='^([A-Za-z][A-Za-z0-9+.-]*)://([^/@[:space:]]+)@'
    if [[ $1 =~ $re ]]; then
        local scheme="${BASH_REMATCH[1],,}" userinfo="${BASH_REMATCH[2]}"
        [[ $scheme == http* || $userinfo == *:* ]]
        return
    fi
    return 1
}

parse_remote() { # parse_remote URL -> R_HOST R_OWNER R_NAME; fails when not GitHub-style
    local line
    if ! line="$("$PY" "$HERE/gitflow_github.py" parse-remote -- "$1")"; then return 1; fi
    IFS=$'\t' read -r R_HOST R_OWNER R_NAME <<<"$line"
}

github_remote() { # -> R_HOST R_OWNER R_NAME REMOTE_URL_RAW
    gx config --get "remote.$REMOTE.url"
    if ((GRC != 0)) || [[ -z $GOUT ]]; then die "remote '$REMOTE' is not configured" "Add it: git remote add $REMOTE <github https url>"; fi
    REMOTE_URL_RAW="$GOUT"
    if ! parse_remote "$REMOTE_URL_RAW"; then
        die "remote '$REMOTE' ($REMOTE_URL_RAW) is not a GitHub-style URL" "Pull requests need a GitHub remote such as git@github.com:OWNER/REPO.git."
    fi
}

gh_authenticated() { # gh_authenticated HOST
    if [[ -n $TIMEOUT_BIN ]]; then
        "$TIMEOUT_BIN" 30 gh auth status --hostname "$1" >/dev/null 2>&1
    else
        gh auth status --hostname "$1" >/dev/null 2>&1
    fi
}

ls_remote_sha() { # ls_remote_sha BRANCH [REMOTE_OR_URL] -> REMOTE_SHA (empty when the branch is not there)
    local sha ref
    git_net 3 ls-remote "${2:-$REMOTE}" "refs/heads/$1"
    if ((GRC != 0)); then git_die ls-remote; fi
    REMOTE_SHA=""
    while IFS=$'\t' read -r sha ref; do
        if [[ $ref == "refs/heads/$1" ]]; then REMOTE_SHA="$sha"; fi
    done <<<"$GOUT"
}

validate_branch_name() {
    local name="$1"
    if [[ -z $name || $name == -* || $name == @* ]]; then die "invalid branch name '$name'"; fi
    gx check-ref-format --branch "$name"
    if ((GRC != 0)) || [[ $GOUT != "$name" ]]; then
        die "invalid branch name '$name'" "Use something like feat/short-description or fix/issue-123 (no spaces, '..', '~', '^', ':', '?', '*', '[')."
    fi
}

fetch_remote() { # -> FETCHED FETCH_WARNING
    FETCHED=false
    FETCH_WARNING=""
    if ! has_remote "$REMOTE"; then
        FETCH_WARNING="no remote named '$REMOTE'; using local refs"
        return 0
    fi
    git_net 3 fetch --prune --quiet "$REMOTE"
    if ((GRC != 0)); then
        FETCH_WARNING="fetch from $REMOTE failed ($(last_error_line "$GERR")); the base may be stale"
        return 0
    fi
    FETCHED=true
    if ! ref_exists "refs/remotes/$REMOTE/HEAD"; then
        # Records the remote's default branch locally so later commands know it.
        git_net 2 remote set-head "$REMOTE" --auto
    fi
}

resolve_base() { # resolve_base [FROM] -> BASE_REF BASE_SHA
    local candidate
    if [[ -n ${1-} ]]; then
        rev "$1"
        if [[ -z $REV ]]; then die "base '$1' does not name a commit" "Fetch first or pass an existing branch, tag or sha to --from."; fi
        BASE_REF="$1"
        BASE_SHA="$REV"
        return 0
    fi
    default_branch
    for candidate in "$REMOTE/$DEFAULT_BRANCH" "$DEFAULT_BRANCH"; do
        rev "$candidate"
        if [[ -n $REV ]]; then
            BASE_REF="$candidate"
            BASE_SHA="$REV"
            return 0
        fi
    done
    die "cannot find the default branch '$DEFAULT_BRANCH' locally or on $REMOTE" "Pass --from REF, or make an initial commit first."
}

normalize_paths() { # normalize_paths RAW... -> PATHS (repository-root-relative)
    PATHS=()
    local raw rel parent name real_root
    real_root="$(cd -- "$REPO" && pwd -P)"
    for raw in "$@"; do
        if [[ -z $raw ]]; then continue; fi
        if [[ $raw == /* ]]; then
            parent="${raw%/*}"
            name="${raw##*/}"
            if [[ -z $parent ]]; then parent=/; fi
            if ! parent="$(cd -- "$parent" 2>/dev/null && pwd -P)"; then die "path '$raw' does not exist"; fi
            rel="$parent/$name"
            if [[ $rel == "$real_root" || $rel == "$real_root/" ]]; then
                rel="."
            elif [[ $rel == "$real_root/"* ]]; then
                rel="${rel#"$real_root"/}"
            else
                die "path '$raw' is outside the repository $REPO"
            fi
        else
            rel="$raw"
            while [[ $rel == ./* ]]; do rel="${rel#./}"; done
            while [[ $rel == */ && $rel != / ]]; do rel="${rel%/}"; done
            if [[ /$rel/ == */../* ]]; then die "path '$raw' is outside the repository (paths are relative to the repository root)"; fi
            if [[ -z $rel ]]; then rel="."; fi
        fi
        PATHS+=("$rel")
    done
}

stamp_now() { # -> STAMP_ID (UTC, milliseconds, after every existing checkpoint id) and STAMP_ISO
    local rt="${EPOCHREALTIME-}" secs ms="000" now latest
    if [[ -n $rt ]]; then
        secs="${rt%[.,]*}"
        ms="${rt#*[.,]}"
        ms="${ms:0:3}"
    elif now="$(date +%s%N 2>/dev/null)" && [[ $now =~ ^[0-9]{19,}$ ]]; then
        # bash before 5.0 has no EPOCHREALTIME; GNU date knows the sub-second part.
        secs="${now:0:${#now}-9}"
        ms="${now:${#now}-9:3}"
    else
        printf -v secs '%(%s)T' -1
    fi
    TZ=UTC0 printf -v STAMP_ID '%(%Y%m%dT%H%M%S)T' "$secs"
    STAMP_ID+="$ms"
    TZ=UTC0 printf -v STAMP_ISO '%(%Y-%m-%dT%H:%M:%SZ)T' "$secs"
    # Ids must sort in creation order even when the clock has no sub-second part
    # or steps back: never go below the newest id, take the next millisecond.
    gx for-each-ref --sort=-refname --count=1 '--format=%(refname:lstrip=2)' "$CHECKPOINT_NS"
    latest="${GOUT:0:18}"
    if [[ $latest =~ ^[0-9]{8}T[0-9]{9}$ && ! $STAMP_ID > $latest ]]; then
        if ((10#${latest:15:3} < 999)); then
            printf -v STAMP_ID '%s%03d' "${latest:0:15}" $((10#${latest:15:3} + 1))
        else
            STAMP_ID="$latest"
        fi
    fi
    STAMP_ID+="Z"
}

trim() {
    local text="$1"
    text="${text#"${text%%[![:space:]]*}"}"
    text="${text%"${text##*[![:space:]]}"}"
    printf '%s' "$text"
}

# ------------------------------------------------------------- checkpoints

new_temp_index() { # -> TMP_INDEX, a not-yet-existing index path inside the git directory
    g rev-parse --absolute-git-dir
    TMP_INDEX="$GOUT/deerflow-tmp-index-$$-$RANDOM$RANDOM"
    CLEANUP+=("$TMP_INDEX")
}

drop_temp_index() {
    GIT_INDEX_OVERRIDE=""
    rm -f -- "$TMP_INDEX" "$TMP_INDEX.lock"
}

unflag_present_entries() { # in the temporary index: let git add read files hidden by index flags
    # A copied index keeps skip-worktree and assume-unchanged bits, and git add
    # then records the HEAD blob instead of the local edit. Re-insert those
    # entries without flags and without stat data, so git add hashes the file on
    # disk. Files that a sparse checkout left out keep their bit.
    local record tag path
    g_file "$TMP/flags" ls-files -v -s -z
    : >"$TMP/flags.reset"
    while IFS= read -r -d '' record; do
        tag="${record:0:1}"
        path="${record#*$'\t'}"
        case "$tag" in
        S | [a-z]) ;;
        *) continue ;;
        esac
        if [[ -e $REPO/$path || -L $REPO/$path ]]; then printf '%s\0' "${record:2}" >>"$TMP/flags.reset"; fi
    done <"$TMP/flags"
    if [[ -s $TMP/flags.reset ]]; then
        GIT_STDIN="$TMP/flags.reset"
        g update-index -z --index-info
        GIT_STDIN=""
    fi
}

create_checkpoint() { # create_checkpoint MESSAGE [FORCE_FILE]: snapshot $REPO -> CK_* (HEAD and the index untouched)
    # FORCE_FILE lists (NUL-separated) files to include even when they are ignored.
    local message head branch real_index tree commit subject
    message="$(trim "${1-}")"
    rev HEAD
    head="$REV"
    current_branch
    branch="$BRANCH"
    new_temp_index
    g rev-parse --git-path index
    real_index="$GOUT"
    if [[ $real_index != /* ]]; then real_index="$REPO/$real_index"; fi
    local copied=false
    if [[ -f $real_index ]] && cp -- "$real_index" "$TMP_INDEX" 2>/dev/null; then copied=true; fi
    GIT_INDEX_OVERRIDE="$TMP_INDEX"
    if [[ $copied == false && -n $head ]]; then g read-tree "$head"; fi
    if [[ $copied == true ]]; then unflag_present_entries; fi
    g add -A -- .
    if [[ -n ${2-} && -s ${2-} ]]; then g add -f --pathspec-from-file="$2" --pathspec-file-nul; fi
    g write-tree
    tree="$GOUT"
    drop_temp_index
    stamp_now
    subject="deerflow checkpoint: ${message:-manual}"
    printf '%s\n\nbranch: %s\nhead: %s\nworktree: %s\ncreated: %s\n' "$subject" "${branch:-(detached)}" "${head:-(none)}" "$REPO" "$STAMP_ISO" >"$TMP/checkpoint.msg"
    local -a ident=() parent=()
    gx config --get user.email
    if ((GRC != 0)) || [[ -z $GOUT ]]; then ident=(-c "user.name=DeerFlow checkpoint" -c "user.email=checkpoint@deerflow.invalid"); fi
    if [[ -n $head ]]; then parent=(-p "$head"); fi
    g "${ident[@]}" commit-tree --no-gpg-sign "$tree" "${parent[@]}" -F "$TMP/checkpoint.msg"
    commit="$GOUT"
    CK_ID="$STAMP_ID-${commit:0:8}"
    g update-ref -m "deerflow checkpoint" "$CHECKPOINT_NS$CK_ID" "$commit"
    CK_SAME=false
    if [[ -n $head ]]; then
        g rev-parse "$head^{tree}"
        if [[ $GOUT == "$tree" ]]; then CK_SAME=true; fi
    fi
    g_file "$TMP/checkpoint.tree" ls-tree -r --name-only -z "$tree"
    local -a names=()
    mapfile -d '' -t names <"$TMP/checkpoint.tree"
    CK_FILES=${#names[@]}
    CK_COMMIT="$commit"
    CK_TREE="$tree"
    CK_HEAD="$head"
    CK_BRANCH="$branch"
    CK_SUBJECT="$subject"
}

dir_is_empty() { # the script never sets these glob options elsewhere
    local -a entries=()
    shopt -s nullglob dotglob
    entries=("$1"/*)
    shopt -u nullglob dotglob
    ((${#entries[@]} == 0))
}

put_checkpoint() {
    put id "$CK_ID"
    put ref "$CHECKPOINT_NS$CK_ID"
    put commit "$CK_COMMIT"
    put tree "$CK_TREE"
    put_opt head "$CK_HEAD"
    put_opt branch "$CK_BRANCH"
    put message "$CK_SUBJECT"
    put_num files "$CK_FILES"
    put_bool same_as_head "$CK_SAME"
}

resolve_checkpoint() { # resolve_checkpoint ID|latest|prefix -> T_ID T_COMMIT
    local want="$1" id commit i
    local -a ids=() commits=() matches=()
    g_file "$TMP/checkpoint.list" for-each-ref --sort=-refname '--format=%(refname:lstrip=2) %(objectname)' "$CHECKPOINT_NS"
    while read -r id commit; do
        ids+=("$id")
        commits+=("$commit")
    done <"$TMP/checkpoint.list"
    if ((${#ids[@]} == 0)); then die "there are no checkpoints in this repository" "Create one with: gitflow.sh checkpoint -m '<what you are about to try>'"; fi
    if [[ $want == latest ]]; then
        T_ID="${ids[0]}"
        T_COMMIT="${commits[0]}"
        return 0
    fi
    want="${want#"$CHECKPOINT_NS"}"
    for i in "${!ids[@]}"; do
        if [[ ${ids[i]} == "$want" ]]; then
            T_ID="${ids[i]}"
            T_COMMIT="${commits[i]}"
            return 0
        fi
    done
    for i in "${!ids[@]}"; do
        if [[ ${ids[i]} == "$want"* || ${commits[i]} == "$want"* ]]; then matches+=("$i"); fi
    done
    if ((${#matches[@]} == 1)); then
        T_ID="${ids[matches[0]]}"
        T_COMMIT="${commits[matches[0]]}"
        return 0
    fi
    if ((${#matches[@]} == 0)); then die "no checkpoint matches '$want'" "List them with: gitflow.sh checkpoints"; fi
    for i in "${matches[@]}"; do _rec "$ERR" a matches "${ids[i]}"; done
    die "'$want' matches ${#matches[@]} checkpoints; use the full id"
}

delete_in_repo() { # delete_in_repo REL: remove one file or symlink inside $REPO, then empty parent directories
    local rel="$1" dir
    case "/$rel/" in
    //* | */../* | */./*) return 0 ;; # only plain repository-relative paths, as git lists them
    esac
    # A symlink in a leading component would lead outside the repository (or to
    # another path in it): never delete through one.
    dir="$rel"
    while [[ $dir == */* ]]; do
        dir="${dir%/*}"
        if [[ -L $REPO/$dir ]]; then
            KEPT_BEHIND_LINK+=("$rel")
            return 0
        fi
    done
    if [[ -L $REPO/$rel || -f $REPO/$rel ]]; then
        rm -f -- "$REPO/$rel"
        DELETED+=("$rel")
        dir="$rel"
        while [[ $dir == */* ]]; do
            dir="${dir%/*}"
            rmdir -- "$REPO/$dir" 2>/dev/null || break
        done
    fi
}

# ---------------------------------------------------------------- commands

common_arg() { # handles --repo, --remote and --help; sets NSHIFT (0 when not a common option)
    NSHIFT=0
    case "$1" in
    --repo)
        if (($# < 2)); then usage_error "--repo needs a value"; fi
        REPO_ARG="$2"
        NSHIFT=2
        ;;
    --remote)
        if (($# < 2)); then usage_error "--remote needs a value"; fi
        REMOTE="$2"
        NSHIFT=2
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    esac
}

need_value() { if (($# < 2)); then usage_error "$1 needs a value"; fi; }

cmd_preflight() {
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        usage_error "unknown argument '$1'"
    done
    resolve_repo
    g_file "$TMP/status" status --porcelain=v2 --branch -z --untracked-files=all
    default_branch_net
    current_branch
    local url="" host="github.com" parsed=false gh_installed=false gh_auth=false names usable
    gx config --get "remote.$REMOTE.url"
    if ((GRC == 0)); then url="$GOUT"; fi
    if [[ -n $url ]] && parse_remote "$url"; then
        parsed=true
        host="$R_HOST"
    fi
    if type -P gh >/dev/null; then
        gh_installed=true
        if gh_authenticated "$host"; then gh_auth=true; fi
    fi
    names="$("$PY" "$HERE/gitflow_github.py" token-names)"
    usable="$("$PY" "$HERE/gitflow_github.py" token-names "--host=$host")"
    operation_in_progress
    common_dir
    g rev-parse --absolute-git-dir
    local git_dir
    git_dir="$(cd -- "$GOUT" && pwd -P)"
    g_file "$TMP/refs" for-each-ref '--format=%(refname)' "$CHECKPOINT_NS"
    local -a checkpoint_refs=()
    mapfile -t checkpoint_refs <"$TMP/refs"

    put repo_root "$REPO"
    _rec "$OUT" P status "$TMP/status"
    put default_branch "$DEFAULT_BRANCH"
    put default_branch_source "$DEFAULT_SOURCE"
    put_bool on_default_branch "$(bool test "$BRANCH" = "$DEFAULT_BRANCH")"
    put_opt operation_in_progress "$OPERATION"
    put remote "$REMOTE"
    put_opt remote_url "$url"
    put_bool remote_url_has_credentials "$(bool url_has_credentials "$url")"
    if [[ $parsed == true ]]; then
        put github_repo "$R_OWNER/$R_NAME"
        put github_host "$R_HOST"
    else
        put_null github_repo
        put_null github_host
    fi
    _rec "$OUT" j gh "{\"installed\": $gh_installed, \"authenticated\": $gh_auth}"
    put_list token_env
    local name
    for name in $names; do add token_env "$name"; done
    put_bool token_present "$(bool test -n "$names")"
    # What pr create and pr status would authenticate with for this remote.
    if [[ $parsed == true && -n $usable ]]; then
        put github_auth "${usable%% *}"
    elif [[ $parsed == true && $gh_auth == true ]]; then
        put github_auth gh
    else
        put_null github_auth
    fi
    put_bool linked_worktree "$(bool test "$git_dir" != "$COMMON")"
    put_num checkpoints "${#checkpoint_refs[@]}"
    put_list warnings
    if [[ -z $BRANCH ]]; then
        warn "HEAD is detached: create a branch before committing (gitflow.sh branch NAME)"
    elif is_protected "$BRANCH"; then
        warn "on protected branch '$BRANCH': create a work branch before committing (gitflow.sh branch NAME)"
    fi
    if url_has_credentials "$url"; then
        warn "remote '$REMOTE' URL embeds credentials; replace it with a plain URL (git remote set-url $REMOTE <url without credentials>) and rely on the credential helper"
    fi
    if [[ -n $OPERATION ]]; then warn "a $OPERATION is in progress; finish or abort it before other git operations"; fi
    gx diff --name-only --diff-filter=U
    if [[ -n $GOUT ]]; then warn "unresolved merge conflicts are present"; fi
    if [[ $parsed == true && $gh_auth == false && -z $usable ]]; then
        if [[ ${host,,} != github.com && -n $names ]]; then
            warn "GH_TOKEN and GITHUB_TOKEN are only sent to github.com; pull requests on $host need GH_ENTERPRISE_TOKEN with $host listed in GITFLOW_GITHUB_HOSTS, or gh logged in to $host"
        else
            warn "no GitHub credentials found (gh is not authenticated and no token variable is set), so pushes over https and pull requests will fail"
        fi
    fi
    warn_default_unknown
    finish
}

cmd_branch() {
    local name="" from=""
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --from)
            need_value "$@"
            from="$2"
            shift 2
            ;;
        -*) usage_error "unknown argument '$1'" ;;
        *)
            if [[ -n $name ]]; then usage_error "unexpected argument '$1'"; fi
            name="$1"
            shift
            ;;
        esac
    done
    if [[ -z $name ]]; then usage_error "branch needs a NAME"; fi
    resolve_repo
    validate_branch_name "$name"
    fetch_remote
    default_branch
    if is_protected "$name"; then die "'$name' is a protected branch; work on a feature branch" "Pick a name such as feat/<topic> or fix/<topic>."; fi
    _git_exec "$TMP/carried" "$REPO" diff --name-only -z HEAD
    if ((GRC != 0)); then : >"$TMP/carried"; fi # no commits yet
    local created source base_ref="" base_sha=""
    if ref_exists "refs/heads/$name"; then
        created=false
        source="existing local branch"
        current_branch
        if [[ $BRANCH != "$name" ]]; then g switch "$name"; fi
    elif ref_exists "refs/remotes/$REMOTE/$name"; then
        created=true
        source="$REMOTE/$name"
        base_ref="$REMOTE/$name"
        rev "$base_ref"
        base_sha="$REV"
        g switch -c "$name" --track "$REMOTE/$name"
    else
        resolve_base "$from"
        created=true
        source="new branch"
        base_ref="$BASE_REF"
        base_sha="$BASE_SHA"
        g switch --no-track -c "$name" "$base_sha"
    fi
    current_branch
    put branch "$BRANCH"
    put_bool created "$created"
    put source "$source"
    put_opt base "$base_ref"
    put_opt base_sha "$base_sha"
    rev HEAD
    put_opt head "$REV"
    put_bool fetched "$FETCHED"
    gx rev-parse --abbrev-ref --symbolic-full-name "@{upstream}"
    if ((GRC == 0)); then put upstream "$GOUT"; else put_null upstream; fi
    add_file_z carried_changes "$TMP/carried"
    put_list warnings
    if [[ -n $FETCH_WARNING ]]; then warn "$FETCH_WARNING"; fi
    finish
}

cmd_checkpoint() {
    local message=""
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        -m | --message)
            need_value "$@"
            message="$2"
            shift 2
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    resolve_repo
    create_checkpoint "$message"
    put_checkpoint
    finish
}

cmd_checkpoints() {
    local limit=50
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --limit)
            need_value "$@"
            limit="$2"
            shift 2
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    if [[ ! $limit =~ ^[0-9]+$ ]]; then usage_error "--limit needs a number"; fi
    resolve_repo
    g_file "$TMP/checkpoints" for-each-ref --sort=-refname "--format=$CK_FORMAT" "$CHECKPOINT_NS"
    _rec "$OUT" P checkpoints "$TMP/checkpoints"$'\n'"$limit"
    finish
}

cmd_restore() {
    local id="" clean=false file
    local -a raw_paths=()
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --clean)
            clean=true
            shift
            ;;
        --paths)
            shift
            # The list ends at the next option (anything starting with '-').
            while (($#)) && [[ $1 != -* ]]; do
                raw_paths+=("$1")
                shift
            done
            if ((${#raw_paths[@]} == 0)); then usage_error "--paths needs at least one path"; fi
            ;;
        -*) usage_error "unknown argument '$1'" ;;
        *)
            if [[ -n $id ]]; then usage_error "unexpected argument '$1'"; fi
            id="$1"
            shift
            ;;
        esac
    done
    if [[ -z $id ]]; then usage_error "restore needs a checkpoint ID (or latest)"; fi
    resolve_repo
    resolve_checkpoint "$id"
    normalize_paths "${raw_paths[@]}"
    local -a spec=("${PATHS[@]}") restored=() current=() blocked=()
    if ((${#spec[@]} == 0)); then spec=(.); fi
    # What the checkpoint would write, before anything changes.
    new_temp_index
    GIT_INDEX_OVERRIDE="$TMP_INDEX"
    g read-tree "$T_COMMIT"
    g_file "$TMP/restore.files" ls-files -z -- "${spec[@]}"
    drop_temp_index
    mapfile -d '' -t restored <"$TMP/restore.files"
    if ((${#PATHS[@]})) && ((${#restored[@]} == 0)) && [[ $clean == false ]]; then
        die "none of the given paths exist in the checkpoint" "Check the names with: git ls-tree -r --name-only $T_COMMIT"
    fi
    # git would remove a directory, or a file or symlink standing where the
    # checkpoint has a directory, to write these files. Ignored files and nested
    # repositories inside them are in no checkpoint, so refuse instead.
    local prefix rest target
    local -A in_way=()
    : >"$TMP/restore.existing"
    for file in "${restored[@]}"; do
        prefix=""
        rest="$file"
        while [[ $rest == */* ]]; do
            prefix="${prefix:+$prefix/}${rest%%/*}"
            rest="${rest#*/}"
            if [[ -L $REPO/$prefix || (-e $REPO/$prefix && ! -d $REPO/$prefix) ]]; then
                in_way["$prefix"]=1
                continue 2
            fi
        done
        target="$REPO/$file"
        if [[ -d $target && ! -L $target ]]; then
            if ! dir_is_empty "$target"; then in_way["$file"]=1; fi
        elif [[ -e $target || -L $target ]]; then
            printf '%s\0' "$file" >>"$TMP/restore.existing"
        fi
    done
    # The safety checkpoint must keep every file this restore overwrites. git add
    # skips ignored files, so those few are added by name, with force.
    : >"$TMP/restore.force"
    if [[ -s $TMP/restore.existing ]]; then
        GIT_STDIN="$TMP/restore.existing"
        # check-ignore rejects the literal-pathspec setting; it reads stdin paths literally anyway.
        GIT_LITERAL_PATHSPECS=0 _git_exec "$TMP/restore.force" "$REPO" check-ignore -z --stdin
        GIT_STDIN=""
        if ((GRC > 1)); then git_die check-ignore; fi # 1 only means: none is ignored
    fi
    if ((${#in_way[@]})); then
        for file in "${!in_way[@]}"; do blocked+=("$file"); done
        for file in "${blocked[@]}"; do _rec "$ERR" a blocked_paths "$file"; done
        die "restore would remove paths that are in the way: ${blocked[*]}" "A directory (or a file or symlink where the checkpoint has a directory) stands where the checkpoint has a file. Check its contents, move it aside yourself, then restore again."
    fi
    create_checkpoint "before restore of $T_ID" "$TMP/restore.force"
    local safety="$CK_ID"
    if [[ -s $TMP/restore.files ]]; then
        new_temp_index
        GIT_INDEX_OVERRIDE="$TMP_INDEX"
        g read-tree "$T_COMMIT"
        GIT_STDIN="$TMP/restore.files"
        g checkout-index -f -z --stdin
        GIT_STDIN=""
        drop_temp_index
    fi
    DELETED=()
    KEPT_BEHIND_LINK=()
    if [[ $clean == true ]]; then
        local -A keep=() seen=()
        for file in "${restored[@]}"; do keep["$file"]=1; done
        g_file "$TMP/restore.current" ls-files -z --cached --others --exclude-standard -- "${spec[@]}"
        mapfile -d '' -t current <"$TMP/restore.current"
        for file in "${current[@]}"; do
            if [[ -z $file || -n ${keep["$file"]-} || -n ${seen["$file"]-} ]]; then continue; fi
            seen["$file"]=1
            delete_in_repo "$file"
        done
    fi
    put id "$T_ID"
    put commit "$T_COMMIT"
    put_list paths
    for file in "${PATHS[@]}"; do add paths "$file"; done
    add_file_z restored "$TMP/restore.files"
    put_num restored_count "${#restored[@]}"
    put_list deleted
    for file in "${DELETED[@]}"; do add deleted "$file"; done
    put_num deleted_count "${#DELETED[@]}"
    put safety_checkpoint "$safety"
    local undo="restore $safety"
    if [[ $clean == true ]]; then undo+=" --clean"; fi
    put note "HEAD and the index are unchanged; restored files show up as working-tree changes. Undo with: $undo"
    put_list warnings
    for file in "${KEPT_BEHIND_LINK[@]}"; do
        warn "kept $file: a leading directory of it is a symlink, and deleting through it could reach outside the repository"
    done
    finish
}

cmd_commit() {
    local all=false allow=false message_file="" message="" have_file=false
    local -a messages=() raw_paths=()
    local paths_given=false
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        -m | --message)
            need_value "$@"
            messages+=("$2")
            shift 2
            ;;
        --message-file)
            need_value "$@"
            message_file="$2"
            have_file=true
            shift 2
            ;;
        --paths)
            paths_given=true
            shift
            # The list ends at the next option (anything starting with '-').
            while (($#)) && [[ $1 != -* ]]; do
                raw_paths+=("$1")
                shift
            done
            ;;
        --all)
            all=true
            shift
            ;;
        --allow-default-branch)
            allow=true
            shift
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    if ((${#messages[@]})) && [[ $have_file == true ]]; then usage_error "use either -m or --message-file"; fi
    if ((${#messages[@]} == 0)) && [[ $have_file == false ]]; then usage_error "commit needs -m MSG or --message-file FILE"; fi
    if [[ $paths_given == true && $all == true ]]; then usage_error "use either --paths or --all"; fi
    if [[ $paths_given == true ]] && ((${#raw_paths[@]} == 0)); then usage_error "--paths needs at least one path"; fi
    resolve_repo
    if [[ $have_file == true ]]; then
        if [[ $message_file == - ]]; then
            IFS= read -r -d '' message || true
        elif [[ -r $message_file && -f $message_file ]]; then
            IFS= read -r -d '' message <"$message_file" || true
        else
            die "cannot read message file $message_file"
        fi
    else
        local part
        for part in "${messages[@]}"; do
            if [[ -n $message ]]; then message+=$'\n\n'; fi
            message+="$part"
        done
    fi
    if [[ -z ${message//[[:space:]]/} ]]; then die "the commit message is empty"; fi
    current_branch
    local branch="$BRANCH"
    if [[ -z $branch ]]; then die "HEAD is detached; commits made here are easy to lose" "Create a branch first: gitflow.sh branch NAME"; fi
    default_branch_net
    if is_protected "$branch" && [[ $allow == false ]]; then
        die "refusing to commit on protected branch '$branch'" "Create a work branch first (gitflow.sh branch feat/<topic>); pass --allow-default-branch only when the user asked for a commit on this branch."
    fi
    operation_in_progress
    case "$OPERATION" in
    rebase | cherry-pick | revert | bisect) die "a $OPERATION is in progress" "Finish or abort it with git before committing." ;;
    esac
    g_file "$TMP/conflicts" diff --name-only -z --diff-filter=U
    if [[ -s $TMP/conflicts ]]; then
        local item
        while IFS= read -r -d '' item; do _rec "$ERR" a conflicted "$item"; done <"$TMP/conflicts"
        die "unresolved merge conflicts" "Resolve them, then include the files in --paths."
    fi
    normalize_paths "${raw_paths[@]}"
    local file
    local -a staged=() outside=() inside_list=()
    if ((${#PATHS[@]})); then
        g_file "$TMP/inside" diff --cached --name-only -z --no-renames -- "${PATHS[@]}"
        g_file "$TMP/all" diff --cached --name-only -z --no-renames
        local -A inside=()
        mapfile -d '' -t inside_list <"$TMP/inside"
        for file in "${inside_list[@]}"; do inside["$file"]=1; done
        mapfile -d '' -t staged <"$TMP/all"
        for file in "${staged[@]}"; do
            if [[ -z ${inside["$file"]-} ]]; then outside+=("$file"); fi
        done
        if ((${#outside[@]})); then
            for file in "${outside[@]}"; do _rec "$ERR" a staged_outside_paths "$file"; done
            die "other changes are already staged outside --paths and would be committed too" "Add them to --paths, or unstage them with: git restore --staged <file>"
        fi
    fi
    if ((${#PATHS[@]})) || [[ $all == true ]]; then
        backup_index
        if ((${#PATHS[@]})); then g add -A -- "${PATHS[@]}"; else g add -A -- .; fi
    fi
    g_file "$TMP/staged" diff --cached --name-only -z --no-renames
    if [[ ! -s $TMP/staged ]]; then die "nothing to commit: no staged changes" "Pass --paths with the files you changed, or --all. Check them with preflight."; fi
    g_file "$TMP/scan.names" diff --cached --name-only -z --no-renames --diff-filter=ACMRT
    # --text: a -diff or binary attribute, a NUL byte or UTF-16 must not hide content from the scan.
    g_file "$TMP/scan.diff" -c core.quotepath=false diff --cached --text --no-color --no-ext-diff --no-textconv --no-renames --unified=0 --src-prefix=a/ --dst-prefix=b/ --diff-filter=ACMRT
    local scan_status=0 summary="" findings=""
    "$PY" "$HERE/gitflow_scan.py" --names "$TMP/scan.names" <"$TMP/scan.diff" >"$TMP/scan.out" || scan_status=$?
    if ((scan_status == 3)); then
        {
            IFS= read -r summary
            IFS= read -r findings
        } <"$TMP/scan.out"
        _rec "$ERR" j findings "$findings"
        die "refusing to commit: possible secrets in staged changes: $summary" "Remove the secret (load it from an environment variable at runtime) or drop the file from the commit. A verified fake value in a test may carry the marker 'pragma: allowlist secret' on its line; tell the user."
    elif ((scan_status != 0)); then
        die "the secret scan failed (exit status $scan_status)"
    fi
    local body="$message"
    while [[ $body == *$'\n' ]]; do body="${body%$'\n'}"; done
    printf '%s\n' "$body" >"$TMP/commit.msg"
    # The message travels on stdin, so no shell quoting can mangle it.
    GIT_STDIN="$TMP/commit.msg"
    g commit --quiet -F -
    GIT_STDIN=""
    SAVED_INDEX=""
    rev HEAD
    local sha="$REV" subject re
    subject="$(trim "$message")"
    subject="${subject%%$'\n'*}"
    g show --shortstat --format= "$sha"
    local stat files_changed=0 insertions=0 deletions=0
    stat="$(trim "$GOUT")"
    re='([0-9]+) files? changed'
    if [[ $stat =~ $re ]]; then files_changed="${BASH_REMATCH[1]}"; fi
    re='([0-9]+) insertions?'
    if [[ $stat =~ $re ]]; then insertions="${BASH_REMATCH[1]}"; fi
    re='([0-9]+) deletions?'
    if [[ $stat =~ $re ]]; then deletions="${BASH_REMATCH[1]}"; fi
    put sha "$sha"
    put short_sha "${sha:0:12}"
    put branch "$branch"
    put subject "$subject"
    add_file_z files "$TMP/staged"
    put shortstat "$stat"
    put_num files_changed "$files_changed"
    put_num insertions "$insertions"
    put_num deletions "$deletions"
    put_list warnings
    if ((${#subject} > 72)); then warn "subject is ${#subject} characters; keep it under 72"; fi
    warn_default_unknown
    finish
}

git_at_least() { # git_at_least MAJOR MINOR
    local re='([0-9]+)\.([0-9]+)'
    gx version
    if [[ $GOUT =~ $re ]]; then
        ((BASH_REMATCH[1] > $1 || (BASH_REMATCH[1] == $1 && BASH_REMATCH[2] >= $2)))
        return
    fi
    return 1
}

cmd_push() {
    local lease=false
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --force-with-lease)
            lease=true
            shift
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    resolve_repo
    current_branch
    local branch="$BRANCH"
    if [[ -z $branch ]]; then die "HEAD is detached; nothing to push" "Create a branch first: gitflow.sh branch NAME"; fi
    default_branch_net
    if is_protected "$branch"; then die "refusing to push protected branch '$branch'" "Push a feature branch and open a pull request."; fi
    if ! has_remote "$REMOTE"; then die "remote '$REMOTE' is not configured"; fi
    rev HEAD
    local head="$REV"
    if [[ -z $head ]]; then die "the branch has no commits yet" "Commit first: gitflow.sh commit -m '...' --paths <files>"; fi
    gx remote get-url --push "$REMOTE"
    local push_url="$GOUT" raw_url=""
    gx config --get "remote.$REMOTE.url"
    if ((GRC == 0)); then raw_url="$GOUT"; fi
    local -a args=(push --porcelain -u)
    if [[ $lease == true ]]; then
        args+=("--force-with-lease=refs/heads/$branch")
        if git_at_least 2 30; then args+=(--force-if-includes); fi
    fi
    args+=("$REMOTE" "refs/heads/$branch:refs/heads/$branch")
    git_net "$PUSH_ATTEMPTS" "${args[@]}"
    # The read-back below is another networked call; keep the push's own numbers.
    local push_attempts="$ATTEMPTS" delays
    delays="$(IFS=,; printf '%s' "${DELAYS[*]}")"
    local flag="" ref summary="" line
    while IFS= read -r line; do
        IFS=$'\t' read -r flag ref summary <<<"$line" || true
        if [[ $ref == *":refs/heads/$branch" ]]; then break; fi
        flag=""
        summary=""
    done <<<"$GOUT"
    if ((GRC != 0)); then
        _rec "$ERR" n attempts "$push_attempts"
        _rec "$ERR" s remote_url "$push_url"
        if [[ -n $summary ]]; then GERR+=$'\n'"$summary"; fi
        git_die push
    fi
    # Read back where the push went: a separate pushurl is not the fetch URL.
    ls_remote_sha "$branch" "${push_url:-$REMOTE}"
    if [[ $REMOTE_SHA != "$head" ]]; then
        _rec "$ERR" s local_sha "$head"
        _rec "$ERR" s remote_sha "$REMOTE_SHA"
        die "push reported success but $REMOTE/$branch is at ${REMOTE_SHA:-nothing}, not local HEAD $head" "Do not report the push as done. Push again, then check with: git ls-remote $REMOTE refs/heads/$branch"
    fi
    local result
    case "$flag" in
    "*") result="new branch" ;;
    "+") result="forced update" ;;
    "=") result="up to date" ;;
    *) result="fast-forward" ;;
    esac
    put remote "$REMOTE"
    put remote_url "$push_url"
    put branch "$branch"
    put local_sha "$head"
    put remote_sha "$REMOTE_SHA"
    put_bool verified true
    put result "$result"
    put_bool forced "$(bool test "$flag" = "+")"
    gx rev-parse --abbrev-ref --symbolic-full-name "@{upstream}"
    if ((GRC == 0)); then put upstream "$GOUT"; else put_null upstream; fi
    put_num attempts "$push_attempts"
    _rec "$OUT" j retry_delays_seconds "[$delays]"
    if [[ -n $raw_url ]] && parse_remote "$raw_url"; then
        put new_pull_request_url "$("$PY" "$HERE/gitflow_github.py" new-pull-url "--host=$R_HOST" "--owner=$R_OWNER" "--repo=$R_NAME" "--branch=$branch")"
    else
        put_null new_pull_request_url
    fi
    put_list warnings
    if url_has_credentials "$push_url"; then warn "remote '$REMOTE' URL embeds credentials; replace it with a plain URL and rely on the credential helper"; fi
    warn_default_unknown
    finish
}

select_auth() { # select_auth HOST -> AUTH_MODE (env or gh); the token variables are scoped by host
    local names message
    names="$("$PY" "$HERE/gitflow_github.py" token-names "--host=$1")"
    if [[ -n ${names//[[:space:]]/} ]]; then
        AUTH_MODE=env
        return 0
    fi
    if type -P gh >/dev/null && gh_authenticated "$1"; then
        AUTH_MODE=gh
        return 0
    fi
    if [[ ${1,,} == github.com ]]; then
        message="no GitHub credentials found (gh is missing or not logged in, and neither GH_TOKEN nor GITHUB_TOKEN is set)"
    else
        message="no GitHub credentials found for $1 (GH_TOKEN and GITHUB_TOKEN are only sent to github.com; for a GitHub Enterprise host, list it in GITFLOW_GITHUB_HOSTS and set GH_ENTERPRISE_TOKEN, or log gh in to it)"
    fi
    die "$message" "Ask the user to connect GitHub (or configure a token for the sandbox). Never ask them to paste a token into chat."
}

run_github() { # run gitflow_github.py with the selected credentials and exit with its status
    local status=0
    trap - ERR
    if [[ -n ${GITFLOW_API_URL-} ]]; then set -- "$@" "--api-url=$GITFLOW_API_URL"; fi
    if [[ $AUTH_MODE == gh ]]; then
        # gh's credentials travel on a pipe, never through argv or the environment.
        gh auth token --hostname "$R_HOST" 2>/dev/null | "$PY" "$HERE/gitflow_github.py" "$@" --auth-from-stdin || status=$?
    else
        "$PY" "$HERE/gitflow_github.py" "$@" || status=$?
    fi
    exit "$status"
}

cmd_pr_create() {
    local title="" title_set=false body="" body_set=false body_file="" base="" draft=false
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --title)
            need_value "$@"
            title="$2"
            title_set=true
            shift 2
            ;;
        --body)
            need_value "$@"
            body="$2"
            body_set=true
            shift 2
            ;;
        --body-file)
            need_value "$@"
            body_file="$2"
            shift 2
            ;;
        --base)
            need_value "$@"
            base="$2"
            shift 2
            ;;
        --draft)
            draft=true
            shift
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    if [[ $title_set == false ]]; then usage_error "--title is required"; fi
    if [[ $body_set == true && -n $body_file ]] || [[ $body_set == false && -z $body_file ]]; then usage_error "pass exactly one of --body and --body-file"; fi
    resolve_repo
    current_branch
    local branch="$BRANCH"
    if [[ -z $branch ]]; then die "HEAD is detached" "Switch to the branch you pushed."; fi
    default_branch_net
    if is_protected "$branch"; then die "the current branch '$branch' is protected; a pull request needs a feature branch as its head"; fi
    title="$(trim "$title")"
    if [[ -z $title ]]; then die "the pull request title is empty"; fi
    local body_path="$TMP/pr-body.md"
    if [[ $body_set == true ]]; then
        printf '%s' "$body" >"$body_path"
    elif [[ $body_file == - ]]; then
        IFS= read -r -d '' body || true
        printf '%s' "$body" >"$body_path"
    elif [[ -r $body_file && -f $body_file ]]; then
        body_path="$body_file"
    else
        die "cannot read body file $body_file"
    fi
    github_remote
    base="${base:-$DEFAULT_BRANCH}"
    if [[ $base == "$branch" ]]; then die "base and head are both '$branch'"; fi
    rev HEAD
    local head="$REV"
    ls_remote_sha "$branch"
    if [[ -z $REMOTE_SHA ]]; then die "branch '$branch' is not on $REMOTE" "Push it first: gitflow.sh push"; fi
    select_auth "$R_HOST"
    # --opt=value: a value such as -WIP- can never be read as an option of the helper.
    local -a args=(pr-create "--host=$R_HOST" "--owner=$R_OWNER" "--repo=$R_NAME" "--head=$branch" "--base=$base" "--title=$title" "--body-file=$body_path" "--remote-sha=$REMOTE_SHA" "--local-sha=$head")
    if [[ $draft == true ]]; then args+=(--draft); fi
    if [[ $REMOTE_SHA != "$head" ]]; then
        args+=("--warning=$REMOTE/$branch is at ${REMOTE_SHA:0:12} but local HEAD is ${head:0:12}; push to update the pull request")
    fi
    run_github "${args[@]}"
}

cmd_pr_status() {
    local number=""
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --number)
            need_value "$@"
            number="$2"
            shift 2
            ;;
        *) usage_error "unknown argument '$1'" ;;
        esac
    done
    if [[ -n $number && ! $number =~ ^[0-9]+$ ]]; then usage_error "--number needs a number"; fi
    resolve_repo
    github_remote
    current_branch
    rev HEAD
    local -a args=(pr-status "--host=$R_HOST" "--owner=$R_OWNER" "--repo=$R_NAME" "--local-sha=$REV")
    if [[ -n $number ]]; then args+=("--number=$number"); fi
    if [[ -n $BRANCH ]]; then
        args+=("--branch=$BRANCH")
    elif [[ -z $number ]]; then
        die "HEAD is detached; pass --number"
    fi
    select_auth "$R_HOST"
    run_github "${args[@]}"
}

# --------------------------------------------------------------- worktrees

main_root() { # -> ROOT (main worktree) and COMMON (its .git directory)
    common_dir
    if [[ ${COMMON##*/} != .git ]]; then die "worktrees need a non-bare repository whose git directory is .git"; fi
    ROOT="${COMMON%/.git}"
}

worktree_target() { # worktree_target NAME -> WT_PATH WT_BRANCH
    local name="$1" re='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
    if [[ ! $name =~ $re || $name == *.lock || $name == *..* ]]; then die "invalid worktree name '$name'" "Use letters, digits, '.', '_' or '-', e.g. api-tests."; fi
    main_root
    WT_PATH="$ROOT/$WORKTREE_DIR/$name"
    WT_BRANCH="$WORKTREE_PREFIX$name"
}

canonical() { if [[ -d $1 ]]; then (cd -- "$1" && pwd -P); else printf '%s' "$1"; fi; }

find_worktree() { # find_worktree PATH -> true when registered; sets WT_HEAD WT_LISTED_BRANCH
    local REPO="$ROOT" line current="" want match=false
    want="$(canonical "$1")"
    WT_HEAD=""
    WT_LISTED_BRANCH=""
    g worktree list --porcelain
    while IFS= read -r line; do
        case "$line" in
        "worktree "*)
            current="${line#worktree }"
            if [[ $(canonical "$current") == "$want" ]]; then match=true; else match=false; fi
            ;;
        "HEAD "*) if [[ $match == true ]]; then WT_HEAD="${line#HEAD }"; fi ;;
        "branch "*) if [[ $match == true ]]; then WT_LISTED_BRANCH="${line#branch refs/heads/}"; fi ;;
        "") if [[ $match == true ]]; then return 0; fi ;;
        esac
    done <<<"$GOUT"
    [[ $match == true ]]
}

ensure_excluded() { # -> EXCLUDE_ADDED
    local file="$COMMON/info/exclude" pattern="/$WORKTREE_DIR/" line missing_newline=false
    EXCLUDE_ADDED=false
    if [[ -f $file ]]; then
        while :; do
            if IFS= read -r line; then
                if [[ $line == "$pattern" ]]; then return 0; fi
            else
                if [[ -n $line ]]; then
                    missing_newline=true
                    if [[ $line == "$pattern" ]]; then return 0; fi
                fi
                break
            fi
        done <"$file"
    fi
    mkdir -p -- "$COMMON/info"
    if [[ $missing_newline == true ]]; then printf '\n' >>"$file"; fi
    printf '%s\n' "$pattern" >>"$file"
    EXCLUDE_ADDED=true
}

is_dirty() { # is_dirty DIR: changes or untracked files whatever the status config, or a state git cannot read
    local REPO="$1"
    gx status --porcelain --untracked-files=all --ignore-submodules=none
    ((GRC != 0)) || [[ -n $GOUT ]]
}

cmd_worktree_add() {
    local name="" from=""
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --from)
            need_value "$@"
            from="$2"
            shift 2
            ;;
        -*) usage_error "unknown argument '$1'" ;;
        *)
            if [[ -n $name ]]; then usage_error "unexpected argument '$1'"; fi
            name="$1"
            shift
            ;;
        esac
    done
    if [[ -z $name ]]; then usage_error "worktree add needs a NAME"; fi
    resolve_repo
    worktree_target "$name"
    REPO="$ROOT"
    validate_branch_name "$WT_BRANCH"
    ensure_excluded
    put name "$name"
    put path "$WT_PATH"
    if find_worktree "$WT_PATH"; then
        put_opt branch "$WT_LISTED_BRANCH"
        put_opt head "$WT_HEAD"
        put_bool created false
        put_bool exclude_added "$EXCLUDE_ADDED"
        put_list warnings
        finish
    fi
    if [[ -e $WT_PATH ]]; then die "$WT_PATH exists but is not a registered worktree" "Pick another name, or remove the directory after checking its contents."; fi
    fetch_remote
    local base_ref="" base_sha=""
    if ref_exists "refs/heads/$WT_BRANCH"; then
        g worktree add "$WT_PATH" "$WT_BRANCH"
    else
        resolve_base "$from"
        base_ref="$BASE_REF"
        base_sha="$BASE_SHA"
        g branch --no-track "$WT_BRANCH" "$base_sha"
        g worktree add "$WT_PATH" "$WT_BRANCH"
    fi
    put branch "$WT_BRANCH"
    put_opt base "$base_ref"
    put_opt base_sha "$base_sha"
    REPO="$WT_PATH"
    rev HEAD
    put_opt head "$REV"
    put_bool created true
    put_bool fetched "$FETCHED"
    put_bool exclude_added "$EXCLUDE_ADDED"
    put_list warnings
    if [[ -n $FETCH_WARNING ]]; then warn "$FETCH_WARNING"; fi
    finish
}

cmd_worktree_remove() {
    local name="" force=false delete_branch=false
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        case "$1" in
        --force)
            force=true
            shift
            ;;
        --delete-branch)
            delete_branch=true
            shift
            ;;
        -*) usage_error "unknown argument '$1'" ;;
        *)
            if [[ -n $name ]]; then usage_error "unexpected argument '$1'"; fi
            name="$1"
            shift
            ;;
        esac
    done
    if [[ -z $name ]]; then usage_error "worktree remove needs a NAME"; fi
    resolve_repo
    worktree_target "$name"
    if ! find_worktree "$WT_PATH"; then die "no worktree named '$name' at $WT_PATH" "List them with: gitflow.sh worktree list"; fi
    local here target
    here="$(pwd -P)"
    target="$(canonical "$WT_PATH")"
    if [[ $here == "$target" || $here == "$target/"* || $(canonical "$REPO") == "$target" ]]; then
        die "cannot remove the worktree you are running in" "Run this from the main checkout (pass --repo)."
    fi
    local checkpoint=""
    if [[ -d $WT_PATH ]] && is_dirty "$WT_PATH"; then
        if [[ $force == false ]]; then
            die "worktree '$name' has uncommitted changes (or git cannot read its state)" "Commit and push them, or pass --force: a checkpoint of the changes is saved first, and the worktree is kept if that fails."
        fi
        local REPO_SAVED="$REPO"
        REPO="$WT_PATH"
        create_checkpoint "before removing worktree $name"
        checkpoint="$CK_ID"
        REPO="$REPO_SAVED"
    fi
    REPO="$ROOT"
    if [[ $force == true ]]; then g worktree remove --force "$WT_PATH"; else g worktree remove "$WT_PATH"; fi
    gx worktree prune
    local branch_deleted=false
    put_list warnings
    if [[ $delete_branch == true ]]; then
        gx branch -d "$WT_BRANCH"
        if ((GRC == 0)); then
            branch_deleted=true
        else
            warn "kept branch '$WT_BRANCH': it is not merged (git branch -D deletes it; push it first if the work matters)"
        fi
    fi
    put name "$name"
    put path "$WT_PATH"
    put_bool removed "$(bool test ! -e "$WT_PATH")"
    put branch "$WT_BRANCH"
    put_bool branch_deleted "$branch_deleted"
    put_opt checkpoint "$checkpoint"
    finish
}

cmd_worktree_list() {
    while (($#)); do
        common_arg "$@"
        if ((NSHIFT)); then
            shift "$NSHIFT"
            continue
        fi
        usage_error "unknown argument '$1'"
    done
    resolve_repo
    main_root
    REPO="$ROOT"
    g_file "$TMP/worktrees" worktree list --porcelain
    : >"$TMP/worktrees.dirty"
    local line path dirty
    while IFS= read -r line; do
        if [[ $line != "worktree "* ]]; then continue; fi
        path="${line#worktree }"
        if [[ ${path%/*} == "$ROOT/$WORKTREE_DIR" && -d $path ]]; then
            dirty="$(bool is_dirty "$path")"
            printf '%s\0%s\0' "$path" "$dirty" >>"$TMP/worktrees.dirty"
        fi
    done <"$TMP/worktrees"
    _rec "$OUT" P worktrees "$TMP/worktrees"$'\n'"$ROOT"$'\n'"$TMP/worktrees.dirty"
    finish
}

# -------------------------------------------------------------------- main

main() {
    if (($# == 0)); then usage_error "missing command"; fi
    local command="$1"
    shift
    case "$command" in
    preflight | branch | checkpoint | checkpoints | restore | commit | push)
        CMD="$command"
        "cmd_$command" "$@"
        ;;
    pr | worktree)
        local sub="${1-}"
        if (($#)); then shift; fi
        CMD="$command $sub"
        case "$command:$sub" in
        pr:create | pr:status | worktree:add | worktree:remove | worktree:list) "cmd_${command}_$sub" "$@" ;;
        *) usage_error "unknown $command subcommand '${sub}'" ;;
        esac
        ;;
    -h | --help | help)
        usage
        exit 0
        ;;
    *) usage_error "unknown command '$command'" ;;
    esac
}

main "$@"
