#!/bin/bash

set -euo pipefail

# pam_env's deprecated user_readenv=1 option, which Debian and Ubuntu enable in
# the openssh-server PAM stack, makes PAM import variables from the
# authenticating user's ~/.pam_environment. In this image /etc/passwd and /home
# are symlinked into the shared jail, so that file is user-writable and every
# PAM module running after pam_env - including the root-executed ones this image
# registers - would observe user-authored variables. Turn the option off
# everywhere, the way Ubuntu's own /etc/pam.d/sudo does.

pam_dir="${1:-/etc/pam.d}"

if [ ! -d "${pam_dir}" ]; then
    echo "PAM configuration directory ${pam_dir} does not exist" >&2
    exit 1
fi

# -L so that a symlinked service file is followed to the file that PAM actually
# reads, and --follow-symlinks so that sed rewrites that file instead of
# replacing the link with a regular one. The same file set is used for the
# assertion below, so nothing can be rewritten but left unchecked, or reported
# but never reached.
mapfile -d '' configs < <(find -L "${pam_dir}" -type f -print0)
for config in "${configs[@]}"; do
    grep -qE 'user_readenv=[^[:space:]]+' "${config}" || continue
    sed -i --follow-symlinks -E 's/(^|[[:space:]])user_readenv=[^[:space:]]+/\1user_readenv=0/g' "${config}"
done

enabled="$(grep -hoE 'user_readenv=[^[:space:]]+' "${configs[@]}" /dev/null | sort -u | grep -vFx 'user_readenv=0' || true)"
if [ -n "${enabled}" ]; then
    echo "PAM user environment reading is still enabled in ${pam_dir}: ${enabled}" >&2
    exit 1
fi
