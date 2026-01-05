#!/bin/bash
# Holbein iOS App - Test Scripts
# Use these to test the app during development

BASE_URL="https://phone.rashbass.org/api/dashboard"

echo "============================================"
echo "Holbein Test Scripts"
echo "============================================"
echo ""

show_help() {
    echo "Usage: ./test_holbein.sh [command]"
    echo ""
    echo "Commands:"
    echo "  quick       - Run quick test (3 seconds)"
    echo "  short       - Run short extended test (~30 seconds)"
    echo "  medium      - Run medium extended test (~60 seconds)"
    echo "  long        - Run long extended test (~90 seconds)"
    echo "  interactive - Start call that stays active for manual testing"
    echo "  end [id]    - End an interactive call"
    echo "  location [id] pending|sent|cancelled - Trigger location event"
    echo "  say [id] caller|ai \"text\" - Add transcript to active call"
    echo "  status      - Show current dashboard status"
    echo ""
    echo "Examples:"
    echo "  ./test_holbein.sh medium"
    echo "  ./test_holbein.sh interactive"
    echo "  ./test_holbein.sh end TEST-abc123"
    echo "  ./test_holbein.sh location TEST-abc123 pending"
    echo "  ./test_holbein.sh say TEST-abc123 caller \"Sono arrivato\""
}

case "$1" in
    quick)
        echo "🚀 Running quick test..."
        curl -s -X POST "$BASE_URL/test" | jq
        ;;
    
    short)
        echo "🚀 Running short extended test (~30 seconds)..."
        echo "   Watch your app for the full conversation!"
        curl -s -X POST "$BASE_URL/test-extended?duration=short" | jq
        ;;
    
    medium)
        echo "🚀 Running medium extended test (~60 seconds)..."
        echo "   Watch your app for the full conversation!"
        curl -s -X POST "$BASE_URL/test-extended?duration=medium" | jq
        ;;
    
    long)
        echo "🚀 Running long extended test (~90 seconds)..."
        echo "   Watch your app for the full conversation!"
        curl -s -X POST "$BASE_URL/test-extended?duration=long" | jq
        ;;
    
    interactive)
        echo "🚀 Starting interactive test call..."
        echo "   Call will stay active until you end it manually."
        result=$(curl -s -X POST "$BASE_URL/test-extended?duration=medium&auto_end=false")
        echo "$result" | jq
        call_sid=$(echo "$result" | jq -r '.call_sid')
        echo ""
        echo "📞 Call started: $call_sid"
        echo ""
        echo "Commands you can use:"
        echo "  End call:        ./test_holbein.sh end $call_sid"
        echo "  Trigger SMS:     ./test_holbein.sh location $call_sid pending"
        echo "  Add transcript:  ./test_holbein.sh say $call_sid caller \"Sono qui\""
        ;;
    
    end)
        if [ -z "$2" ]; then
            echo "❌ Error: Please provide call_sid"
            echo "   Usage: ./test_holbein.sh end TEST-abc123"
            exit 1
        fi
        echo "📴 Ending call $2..."
        curl -s -X POST "$BASE_URL/test-end/$2" | jq
        ;;
    
    location)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo "❌ Error: Please provide call_sid and event type"
            echo "   Usage: ./test_holbein.sh location TEST-abc123 pending"
            echo "   Events: pending, sent, cancelled"
            exit 1
        fi
        echo "📍 Triggering location event '$3' on $2..."
        curl -s -X POST "$BASE_URL/test-location-event/$2?event=$3" | jq
        ;;
    
    say)
        if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
            echo "❌ Error: Please provide call_sid, speaker, and text"
            echo "   Usage: ./test_holbein.sh say TEST-abc123 caller \"Sono arrivato\""
            exit 1
        fi
        encoded_text=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$4'))")
        echo "💬 Adding transcript from $3: \"$4\"..."
        curl -s -X POST "$BASE_URL/test-transcript/$2?speaker=$3&text=$encoded_text" | jq
        ;;
    
    status)
        echo "📊 Dashboard status..."
        curl -s "$BASE_URL/status" | jq
        ;;
    
    *)
        show_help
        ;;
esac