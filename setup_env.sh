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

# Initialize and update git submodules
echo "Initializing git submodules..."
git submodule update --init --recursive

# Setup nanoemoji
if [ -d "nanoemoji" ]; then
    echo "Setting up nanoemoji..."
    cd nanoemoji
    pip install -e .
    cd ..
else
    echo "Warning: nanoemoji directory not found, skipping"
fi

# Install ttf2woff in the conda environment
echo "Installing ttf2woff..."
npm install -g ttf2woff

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Environment setup complete!"
echo "To activate the environment, run: conda activate genFontAPI"
