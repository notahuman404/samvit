#!/usr/bin/env bash
# generate-gerbers.sh
# Exports production Gerber files, drill file, and CPL from motor-driver-16ch.kicad_pcb
# Requires KiCad 7 or 8 installed with kicad-cli on PATH.
#
# Usage (run from repo root):
#   bash hardware/kicad/fab/generate-gerbers.sh
#
# Output:
#   hardware/kicad/fab/gerbers/        ← Gerber + drill files (ZIP this for JLC PCB)
#   hardware/kicad/fab/gerbers.zip     ← Ready-to-upload ZIP
#   hardware/kicad/fab/motor-driver-16ch-cpl.csv  ← SMT component placement list

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KICAD_DIR="$(realpath "${SCRIPT_DIR}/..")"
PCB_FILE="${KICAD_DIR}/motor-driver-16ch.kicad_pcb"
OUT_DIR="${SCRIPT_DIR}/gerbers"

echo "==> Haptic Vest — Gerber Export"
echo "    PCB:    ${PCB_FILE}"
echo "    Output: ${OUT_DIR}"
echo ""

# ── Verify kicad-cli is available ──────────────────────────────────────────────
if ! command -v kicad-cli &>/dev/null; then
  echo "ERROR: kicad-cli not found on PATH."
  echo ""
  echo "Install KiCad 7 or 8, then ensure kicad-cli is available:"
  echo "  macOS:  export PATH=\"/Applications/KiCad/KiCad.app/Contents/MacOS:\$PATH\""
  echo "  Linux:  kicad-cli is usually in /usr/bin/ after 'sudo apt install kicad'"
  echo "  Windows: Add KiCad bin dir to PATH in System Properties"
  exit 1
fi

KICAD_VERSION=$(kicad-cli version 2>&1 | head -1)
echo "    kicad-cli: ${KICAD_VERSION}"
echo ""

# ── Verify PCB file exists ──────────────────────────────────────────────────────
if [[ ! -f "${PCB_FILE}" ]]; then
  echo "ERROR: PCB file not found: ${PCB_FILE}"
  exit 1
fi

# ── Create output directory ────────────────────────────────────────────────────
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

# ── Export Gerber layers ───────────────────────────────────────────────────────
echo "==> Exporting Gerber layers..."
kicad-cli pcb export gerbers \
  --output "${OUT_DIR}/" \
  --layers "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,F.Paste,Edge.Cuts,F.CrtYd,F.Fab" \
  --no-protel-ext \
  --subtract-soldermask \
  --disable-aperture-macros \
  "${PCB_FILE}"

# Layer file naming after export (kicad-cli appends layer names):
#   motor-driver-16ch-F_Cu.gbr       → rename to .GTL (top copper)
#   motor-driver-16ch-B_Cu.gbr       → rename to .GBL (bottom copper)
#   motor-driver-16ch-F_SilkS.gbr    → rename to .GTO (top silkscreen)
#   motor-driver-16ch-B_SilkS.gbr    → rename to .GBO (bottom silkscreen)
#   motor-driver-16ch-F_Mask.gbr     → rename to .GTS (top soldermask)
#   motor-driver-16ch-B_Mask.gbr     → rename to .GBS (bottom soldermask)
#   motor-driver-16ch-F_Paste.gbr    → rename to .GTP (top paste/stencil)
#   motor-driver-16ch-Edge_Cuts.gbr  → rename to .GKO (board outline)

echo "    Gerber layers exported."
echo ""

# ── Rename to Protel/Altium extensions (JLC PCB accepts these) ───────────────
echo "==> Renaming layer files to standard Protel extensions..."
BOARD_BASE="motor-driver-16ch"

mv_if_exists() {
  local src="${OUT_DIR}/${BOARD_BASE}-${1}"
  local dst="${OUT_DIR}/${BOARD_BASE}.${2}"
  if [[ -f "${src}" ]]; then
    mv "${src}" "${dst}"
    echo "    ${src##*/} → ${dst##*/}"
  fi
}

# KiCad 7 uses abbreviated layer names (F_SilkS); KiCad 8 uses full names
# (F_Silkscreen). mv_if_exists is a no-op when the source is absent, so we list
# both spellings to support either toolchain version.
mv_if_exists "F_Cu.gbr"          "GTL"
mv_if_exists "B_Cu.gbr"          "GBL"
mv_if_exists "F_SilkS.gbr"       "GTO"
mv_if_exists "F_Silkscreen.gbr"  "GTO"
mv_if_exists "B_SilkS.gbr"       "GBO"
mv_if_exists "B_Silkscreen.gbr"  "GBO"
mv_if_exists "F_Mask.gbr"        "GTS"
mv_if_exists "B_Mask.gbr"        "GBS"
mv_if_exists "F_Paste.gbr"       "GTP"
mv_if_exists "Edge_Cuts.gbr"     "GKO"
mv_if_exists "F_CrtYd.gbr"       "GML"
mv_if_exists "F_Courtyard.gbr"   "GML"
mv_if_exists "F_Fab.gbr"         "GFA"
mv_if_exists "F_Fabrication.gbr" "GFA"

echo ""

# ── Export drill file ──────────────────────────────────────────────────────────
echo "==> Exporting drill file..."
kicad-cli pcb export drill \
  --output "${OUT_DIR}/" \
  --format excellon \
  --excellon-separate-th \
  --generate-map \
  --map-format gerberx2 \
  --drill-origin absolute \
  --excellon-oval-format route \
  --excellon-units mm \
  "${PCB_FILE}"

echo "    Drill file exported."
echo ""

# ── Export component placement list (CPL) for SMT assembly ───────────────────
echo "==> Exporting component placement list (CPL)..."
CPL_FILE="${SCRIPT_DIR}/motor-driver-16ch-cpl.csv"
kicad-cli pcb export pos \
  --output "${CPL_FILE}" \
  --side front \
  --format csv \
  --units mm \
  --use-drill-file-origin \
  "${PCB_FILE}"

echo "    CPL exported to: ${CPL_FILE}"
echo ""

# ── Create ZIP for upload ─────────────────────────────────────────────────────
echo "==> Creating gerbers.zip..."
ZIP_FILE="${SCRIPT_DIR}/gerbers.zip"
(cd "${OUT_DIR}" && zip -r "${ZIP_FILE}" .)
echo "    ZIP created: ${ZIP_FILE}"
echo "    Size: $(du -sh "${ZIP_FILE}" | cut -f1)"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "==> Done. Files generated:"
echo ""
echo "    For JLC PCB order:"
echo "      Upload: hardware/kicad/fab/gerbers.zip"
echo "      Layers: 2, 100mm x 70mm, 1.6mm FR-4"
echo "      Finish: ENIG recommended (HASL acceptable)"
echo "      Color:  Black PCB / White silkscreen"
echo ""
echo "    For JLC SMT assembly:"
echo "      BOM:    hardware/kicad/fab/bom-jlc.csv"
echo "      CPL:    hardware/kicad/fab/motor-driver-16ch-cpl.csv"
echo ""
echo "    Order 9 boards (one per PCA9685 address 0x40–0x48)."
echo "    Set address jumpers A0–A5 before installing."
echo ""

# ── List output files ─────────────────────────────────────────────────────────
echo "==> Gerber files:"
ls -lh "${OUT_DIR}/"
