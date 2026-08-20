#!/usr/bin/env bash
set -euo pipefail

# Start the png2font Hybrid Node/Python API Server
echo "================================================================="
echo "  🚀 Starting png2font API Server on http://127.0.0.1:8000"
echo "  📦 Node: TypeScript orchestration + Python font tools"
echo "  📦 Conda Environment: genFontAPI"
echo "================================================================="

# Source Conda setup script to enable 'conda activate' inside subshells
if [ -f "/opt/miniconda3/etc/profile.d/conda.sh" ]; then
    source "/opt/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
else
    # Fallback to conda's shell integration hook
    eval "$(conda shell.bash hook)"
fi

# Activate the conda environment for PATH resolution (FontForge, python3, nanoemoji, ttf2woff2, etc.)
conda activate genFontAPI

# Build TypeScript and start Node server
npm run build
npm start
