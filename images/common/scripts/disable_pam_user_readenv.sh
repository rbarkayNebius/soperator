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

shopt -s nullglob
for config in "${pam_dir}"/*; do
    [ -f "${config}" ] || continue
    sed -i -E 's/(^|[[:space:]])user_readenv=[^[:space:]]+/\1user_readenv=0/g' "${config}"
done

enabled="$(grep -rhoE 'user_readenv=[^[:space:]]+' "${pam_dir}" | sort -u | grep -vFx 'user_readenv=0' || true)"
if [ -n "${enabled}" ]; then
    echo "PAM user environment reading is still enabled in ${pam_dir}: ${enabled}" >&2
    exit 1
fi
