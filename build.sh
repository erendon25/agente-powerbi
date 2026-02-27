#!/bin/bash
# Script de construcción para Render
# Instala las dependencias de Python
pip install -r requirements.txt

# Instala el navegador Chromium SIN dependencias del sistema (no requiere sudo)
playwright install chromium
