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

echo "Environment setup complete!"
echo "To activate the environment, run: conda activate genFontAPI"
