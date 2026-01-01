#!/bin/bash
# Italian Phone Proxy - Setup Script
# Creates necessary directories and sets permissions

set -e

echo "🇮🇹 Italian Phone Proxy - Setup"
echo "================================"

# Create directory structure
echo "Creating directories..."

mkdir -p data/config
mkdir -p data/documents/raw
mkdir -p data/documents/processed
mkdir -p data/extractions
mkdir -p data/transcripts
mkdir -p data/whatsapp-session

mkdir -p api/app/routers
mkdir -p api/app/services
mkdir -p api/app/prompts
mkdir -p api/app/models
mkdir -p api/app/static/css
mkdir -p api/app/static/js

mkdir -p whatsapp/src

echo "✓ Directories created"

# Create __init__.py files for Python packages
echo "Creating Python package files..."

touch api/app/__init__.py
touch api/app/routers/__init__.py
touch api/app/services/__init__.py
touch api/app/prompts/__init__.py
touch api/app/models/__init__.py

echo "✓ Package files created"

# Set permissions
echo "Setting permissions..."
chmod -R 755 data/
chmod -R 755 api/
chmod -R 755 scripts/

echo "✓ Permissions set"

# Check for .env file
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo ""
        echo "⚠️  No .env file found. Copy from template:"
        echo "   cp .env.example .env"
        echo "   Then edit .env with your API keys."
    fi
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env"
echo "  2. Edit .env with your API keys"
echo "  3. docker-compose up -d --build"
echo "  4. Open http://localhost:8080/documents.html"
echo ""
