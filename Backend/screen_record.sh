#!/bin/bash
# screen_record.sh — Live Display Recording fuer Dogfooding & Marketing
#
# Usage:
#   ./screen_record.sh              # Startet Aufnahme (Ctrl+C zum Stoppen)
#   ./screen_record.sh 300          # Nimmt 300 Sekunden (5 Min) auf
#   ./screen_record.sh 0 audio      # Mit Audio (Mikrofon)
#   ./screen_record.sh 60 desktop   # Mit Desktop-Audio (System-Sound)
#
# Output: <BRIDGE_ROOT>/Recordings/YYYY-MM-DD_HH-MM-SS.mp4

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RECORDINGS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/Recordings"
DISPLAY_TARGET="${DISPLAY:-:0}"
RESOLUTION="1920x1080"
FRAMERATE="30"
QUALITY="23"        # CRF: 0=lossless, 23=default, 28=smaller file
PRESET="ultrafast"  # ultrafast/fast/medium — CPU vs Qualitaet

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

DURATION="${1:-0}"          # 0 = unbegrenzt (Ctrl+C)
AUDIO_MODE="${2:-none}"     # none / audio / desktop

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

mkdir -p "$RECORDINGS_DIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
OUTPUT_FILE="${RECORDINGS_DIR}/${TIMESTAMP}.mp4"

# Build ffmpeg command
CMD=(ffmpeg -f x11grab -video_size "$RESOLUTION" -framerate "$FRAMERATE" -i "$DISPLAY_TARGET")

# Audio
case "$AUDIO_MODE" in
    audio)
        # Mikrofon
        CMD+=(-f pulse -i "alsa_input.pci-0000_03_00.6.analog-stereo")
        echo "[record] Audio: Mikrofon"
        ;;
    desktop)
        # Desktop/System Audio
        CMD+=(-f pulse -i "alsa_output.pci-0000_03_00.6.analog-stereo.monitor")
        echo "[record] Audio: Desktop-Sound"
        ;;
    *)
        echo "[record] Audio: aus"
        ;;
esac

# Video encoding
CMD+=(-c:v libx264 -preset "$PRESET" -crf "$QUALITY")

# Audio encoding (if audio enabled)
if [[ "$AUDIO_MODE" != "none" ]]; then
    CMD+=(-c:a aac -b:a 128k)
fi

# Duration
if [[ "$DURATION" -gt 0 ]]; then
    CMD+=(-t "$DURATION")
    echo "[record] Dauer: ${DURATION}s"
else
    echo "[record] Dauer: unbegrenzt (Ctrl+C zum Stoppen)"
fi

CMD+=("$OUTPUT_FILE")

# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

echo "[record] Output: $OUTPUT_FILE"
echo "[record] Resolution: $RESOLUTION @ ${FRAMERATE}fps"
echo "[record] Starte Aufnahme..."
echo ""

"${CMD[@]}"

echo ""
echo "[record] Fertig: $OUTPUT_FILE"
ls -lh "$OUTPUT_FILE"
