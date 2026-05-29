#!/usr/bin/env bash
# One-shot Azure Quantum Workspace setup for this project.
#
# Run AFTER `az login` completes. Creates:
#   - resource group "quantum-ecc-rg" in japaneast
#   - quantum workspace "geoalpine-quantum-ws"
#   - Quantinuum provider attached (gets $500 free credit)
#   - storage account required by Azure Quantum
#
# Then writes AZURE_QUANTUM_RESOURCE_ID + AZURE_QUANTUM_LOCATION into .env.
#
# Usage:
#   bash scripts/setup_azure_workspace.sh
#
# To customise: edit the variables at the top.

set -euo pipefail

LOCATION="japaneast"
RG="quantum-ecc-rg"
WS="geoalpine-quantum-ws"
STORAGE="quantumeccstorage$RANDOM"   # must be globally unique, lowercase only

echo "=== Azure Quantum Workspace setup ==="
echo "  location : $LOCATION"
echo "  rg       : $RG"
echo "  workspace: $WS"
echo "  storage  : $STORAGE"
echo

# Confirm we're logged in.
echo "1. Verifying az login..."
az account show --output table

# Show current subscription so we can pick if there are multiple.
echo
echo "2. Active subscription:"
SUB_ID=$(az account show --query id --output tsv)
echo "   $SUB_ID"

# Register Microsoft.Quantum provider (one-time per subscription).
echo
echo "3. Registering Microsoft.Quantum resource provider (one-time)..."
az provider register --namespace Microsoft.Quantum --wait
echo "   ✓ registered"

# Resource group.
echo
echo "4. Creating resource group $RG..."
az group create --name "$RG" --location "$LOCATION" --output none
echo "   ✓ created"

# Storage account (required by Azure Quantum to stage job blobs).
echo
echo "5. Creating storage account $STORAGE (may take ~30s)..."
az storage account create \
  --name "$STORAGE" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --output none
echo "   ✓ created"

# Install the quantum CLI extension if missing.
echo
echo "6. Ensuring az quantum extension is installed..."
az extension add --name quantum --upgrade --yes 2>/dev/null || true
echo "   ✓ done"

# Create the workspace with Quantinuum provider attached.
echo
echo "7. Creating Quantum Workspace $WS with Quantinuum provider..."
az quantum workspace create \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --location "$LOCATION" \
  --storage-account "$STORAGE" \
  --provider-sku-list "quantinuum/payg" \
  --output table
echo "   ✓ workspace created"

# Capture the Resource ID for .env.
RESOURCE_ID=$(az quantum workspace show \
  --resource-group "$RG" \
  --workspace-name "$WS" \
  --location "$LOCATION" \
  --query id --output tsv)

echo
echo "8. Writing credentials to .env..."

# Remove any prior Azure Quantum lines.
ENV_FILE=".env"
if [[ -f "$ENV_FILE" ]]; then
  grep -v -E "^(AZURE_QUANTUM_RESOURCE_ID|AZURE_QUANTUM_LOCATION)=" "$ENV_FILE" \
    > "${ENV_FILE}.tmp" || true
  mv "${ENV_FILE}.tmp" "$ENV_FILE"
fi
{
  echo "AZURE_QUANTUM_RESOURCE_ID=$RESOURCE_ID"
  echo "AZURE_QUANTUM_LOCATION=$LOCATION"
} >> "$ENV_FILE"

echo "   ✓ wrote AZURE_QUANTUM_RESOURCE_ID and AZURE_QUANTUM_LOCATION to .env"

echo
echo "Done. Next:"
echo "  python scripts/azure_quantum_readiness.py"
