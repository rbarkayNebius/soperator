#!/bin/bash

set -euo pipefail

source_file="${1:?source file is required}"
output_root="${2:?output root is required}"
binary_dir="${output_root}/opt/bin/slurm"

mkdir -p "${binary_dir}"
# Statically linked on purpose: pam_exec hands this helper an environment that
# may contain user-authored LD_* variables, and a dynamically linked helper
# would already have honoured them before its first instruction runs.
gcc \
    -std=c11 \
    -O2 \
    -Wall \
    -Wextra \
    -Werror \
    -static \
    -o "${binary_dir}/pam_exec_clean_env" \
    "${source_file}"
chmod 0755 "${binary_dir}/pam_exec_clean_env"

# A program interpreter would mean the dynamic loader runs first, which is
# exactly what the static linking is there to avoid.
if readelf --program-headers "${binary_dir}/pam_exec_clean_env" | grep -q 'INTERP'; then
    echo "pam_exec_clean_env is not statically linked" >&2
    exit 1
fi
