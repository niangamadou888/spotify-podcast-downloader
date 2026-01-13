#!/bin/bash

# Setup script for podcast downloader dependencies

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Setting up podcast downloader dependencies..."
echo ""

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
fi

# Install Node.js if missing (required for podcast-dl)
if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}Installing Node.js...${NC}"
    if [ "$OS" == "macos" ]; then
        if command -v brew &> /dev/null; then
            brew install node
        else
            echo "Please install Homebrew first: https://brew.sh"
            exit 1
        fi
    elif [ "$OS" == "linux" ]; then
        if command -v apt &> /dev/null; then
            sudo apt update && sudo apt install -y nodejs npm
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y nodejs npm
        else
            echo "Please install Node.js manually"
            exit 1
        fi
    fi
else
    echo -e "${GREEN}✓ Node.js is installed${NC}"
fi

# Install FFmpeg if missing
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${YELLOW}Installing FFmpeg...${NC}"
    if [ "$OS" == "macos" ]; then
        brew install ffmpeg
    elif [ "$OS" == "linux" ]; then
        if command -v apt &> /dev/null; then
            sudo apt install -y ffmpeg
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y ffmpeg
        fi
    fi
else
    echo -e "${GREEN}✓ FFmpeg is installed${NC}"
fi

# Install Python if missing (for votify)
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Installing Python 3...${NC}"
    if [ "$OS" == "macos" ]; then
        brew install python
    elif [ "$OS" == "linux" ]; then
        sudo apt install -y python3 python3-pip
    fi
else
    echo -e "${GREEN}✓ Python 3 is installed${NC}"
fi

# Install podcast-dl globally (optional but faster)
echo ""
echo -e "${YELLOW}Installing podcast-dl...${NC}"
npm install -g podcast-dl 2>/dev/null || echo "Using npx for podcast-dl instead"

# Install votify (for Spotify)
echo ""
read -p "Install votify for Spotify downloads? (y/N): " install_votify
if [[ "$install_votify" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Installing votify...${NC}"
    pip3 install votify
    echo ""
    echo -e "${YELLOW}IMPORTANT: To use votify with Spotify, you need:${NC}"
    echo "1. Export cookies from Spotify web player (open.spotify.com)"
    echo "   - Firefox: Use 'Export Cookies' extension"
    echo "   - Chrome: Use 'Get cookies.txt LOCALLY' extension"
    echo "   - Save as 'cookies.txt' in the script directory"
    echo ""
    echo "2. For podcasts only, use --disable-wvd flag (no .wvd file needed)"
    echo ""
    echo -e "${RED}WARNING: Using votify may risk Spotify account suspension.${NC}"
fi

# Make main script executable
chmod +x download-podcast.sh 2>/dev/null || true

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Usage:"
echo "  ./download-podcast.sh <url>"
echo ""
echo "Examples:"
echo "  # Download from RSS feed (recommended)"
echo "  ./download-podcast.sh 'https://feed.podbean.com/planetem/feed.xml'"
echo ""
echo "  # Download from Spotify (requires votify setup)"
echo "  ./download-podcast.sh 'https://open.spotify.com/episode/56AGRQErADHFMlMV4Gm7y4'"
