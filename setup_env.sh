#!/bin/bash
set -e

echo "Setting up png2font_api environment..."

# Create conda environment with Node.js
echo "Creating conda environment 'genFontAPI'..."
conda create -n genFontAPI python=3.11 nodejs -y

# Activate conda environment
echo "Activating conda environment 'genFontAPI'..."
source $(conda info --base)/etc/profile.d/conda.sh
conda activate genFontAPI

# Setup nanoemoji (vendored as a git subtree in ./nanoemoji)
# nanoemoji's setup.py uses setuptools_scm, which normally derives the
# package version from nanoemoji's own git tags via `git describe`. The
# subtree merge squashes that tag history away, so we pin the version
# explicitly (matching the commit vendored in) to avoid a build failure.
if [ -d "nanoemoji" ]; then
    echo "Setting up nanoemoji..."
    cd nanoemoji
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NANOEMOJI=0.15.9 pip install -e .
    cd ..
else
    echo "Warning: nanoemoji directory not found, skipping"
fi

# Install ttf2woff2 in the conda environment
echo "Installing ttf2woff2..."
npm install -g ttf2woff2

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Download and install svgcleaner binary for current OS
echo "Setting up svgcleaner..."
SVGCLEANER_VERSION="0.9.5"
OS_TYPE=$(uname -s)

if [ "$OS_TYPE" = "Darwin" ]; then
    echo "Detected macOS. Downloading svgcleaner for macOS..."
    curl -sL "https://github.com/RazrFalcon/svgcleaner/releases/download/v${SVGCLEANER_VERSION}/svgcleaner_macos_${SVGCLEANER_VERSION}.zip" -o /tmp/svgcleaner.zip
    unzip -o /tmp/svgcleaner.zip svgcleaner -d .
    rm -f /tmp/svgcleaner.zip
    chmod +x ./svgcleaner
    xattr -d com.apple.quarantine ./svgcleaner 2>/dev/null || true
    echo "svgcleaner (macOS) installed to ./svgcleaner"

    # If running on Apple Silicon (arm64), ensure Rosetta 2 is installed for x86_64 binaries
    if [ "$(uname -m)" = "arm64" ]; then
        if ! ./svgcleaner --version &> /dev/null; then
            echo "Apple Silicon detected and svgcleaner requires Rosetta 2. Installing Rosetta..."
            softwareupdate --install-rosetta --agree-to-license || echo "If you see '[Errno 86] Bad CPU type in executable', please run: softwareupdate --install-rosetta"
        fi
    fi

    # Check for FontForge on macOS
    if ! command -v fontforge &> /dev/null; then
        echo "Note: If FontForge installation or compilation fails on macOS, run: brew install cmake glib pango gtk+3"
    fi
elif [ "$OS_TYPE" = "Linux" ]; then
    echo "Detected Linux. Downloading svgcleaner for Linux (x86_64)..."
    curl -sL "https://github.com/RazrFalcon/svgcleaner/releases/download/v${SVGCLEANER_VERSION}/svgcleaner_linux_x86_64_${SVGCLEANER_VERSION}.tar.gz" | tar -xz -C . svgcleaner
    chmod +x ./svgcleaner
    echo "svgcleaner (Linux) installed to ./svgcleaner"
else
    echo "Warning: Unsupported OS ($OS_TYPE) for automatic svgcleaner download. Please install svgcleaner manually."
fi

echo "Environment setup complete!"
echo "To activate the environment, run: conda activate genFontAPI"
