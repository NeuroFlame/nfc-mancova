#!/bin/bash
#
# Run nfc-mancova with real GICA vault data.
# By default uses 20-subject subset vaults (fast).
# Set N_SUBJECTS=0 to use the full vaults (91 + 189 subjects).
#
# Each vault is mounted twice:
#   1. As test_data/site{N}  — so data-dir discovery finds it
#   2. At the original COINSTAC outputDir  — so MATLAB's ICA parameter file
#      can resolve timecourse NIfTI paths without patching the .mat file
#
# To regenerate subset vaults:
#   python3 create_vault_subset.py --n-subjects 20
#   python3 create_vault_subset.py --n-subjects 0   # all subjects (91 + 189)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_WORKSPACE="$SCRIPT_DIR"
REMOTE_WORKSPACE='/workspace'

N_SUBJECTS="${N_SUBJECTS:-20}"

if [ "$N_SUBJECTS" -gt 0 ] 2>/dev/null; then
  CMI_VAULT="/Users/admin/Desktop/Vault Data/CMI-GICA_vault_${N_SUBJECTS}subj"
  TRENDS_VAULT="/Users/admin/Desktop/Vault Data/TReNDS-COBRE-GICA_vault_${N_SUBJECTS}subj"
else
  # N_SUBJECTS=0 → use full-subject subsets (patched mat + truncated NIfTIs)
  CMI_VAULT="/Users/admin/Desktop/Vault Data/CMI-GICA_vault_allsubj"
  TRENDS_VAULT="/Users/admin/Desktop/Vault Data/TReNDS-COBRE-GICA_vault_allsubj"
fi

CMI_MATLAB_PATH="/output/622be18c9db35c30e08aa595/678750199f607a268a4f816d"
TRENDS_MATLAB_PATH="/output/local0/simulator"

echo "Using LOCAL_WORKSPACE: $LOCAL_WORKSPACE"
echo "Using REMOTE_WORKSPACE: $REMOTE_WORKSPACE"
echo ""
echo "site1 vault: $CMI_VAULT"
echo "site2 vault: $TRENDS_VAULT"

MSYS_NO_PATHCONV=1 docker run --rm -it \
    --platform linux/amd64 \
    --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
    --name nfc-mancova-vault \
    -v "$LOCAL_WORKSPACE:$REMOTE_WORKSPACE" \
    -v "$CMI_VAULT:$REMOTE_WORKSPACE/test_data/site1:ro" \
    -v "$CMI_VAULT:$CMI_MATLAB_PATH:ro" \
    -v "$TRENDS_VAULT:$REMOTE_WORKSPACE/test_data/site2:ro" \
    -v "$TRENDS_VAULT:$TRENDS_MATLAB_PATH:ro" \
    -w "$REMOTE_WORKSPACE" \
    -e "PARAMETERS_FILE_PATH=$REMOTE_WORKSPACE/test_data/server/vault_parameters.json" \
    nfc-mancova:dev
