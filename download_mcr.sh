#!/bin/bash
set -e

# Download and install MATLAB Runtime R2016b for use with GIFT standalone.
# This mirrors the COINSTAC MCR installation pattern.

MCR_VERSION="R2016b"
MCR_URL="http://ssd.mathworks.com/supportfiles/downloads/${MCR_VERSION}/deployment_files/${MCR_VERSION}/installers/glnxa64/MCR_R2016b_glnxa64_installer.zip"
INSTALL_DIR="/usr/local/MATLAB/MATLAB_Runtime/v91"
TMP_DIR="/tmp/mcr_installer"

mkdir -p "${TMP_DIR}"
cd "${TMP_DIR}"

if [ ! -f "MCR_R2016b_glnxa64_installer.zip" ]; then
    echo "Downloading MATLAB Runtime ${MCR_VERSION}..."
    wget -O MCR_R2016b_glnxa64_installer.zip "${MCR_URL}"
fi

unzip -o MCR_R2016b_glnxa64_installer.zip
./install -mode silent -agreeToLicense yes || true

if [ -d "/usr/local/MATLAB/MATLAB_Runtime/v91" ]; then
    echo "MATLAB Runtime installed at /usr/local/MATLAB/MATLAB_Runtime/v91"
else
    echo "MATLAB Runtime installer did not create /usr/local/MATLAB/MATLAB_Runtime/v91"
fi
