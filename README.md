# 🪟 VideoStudio Pro — Windows Offline All-in-One Installer Edition

Aplicación de escritorio moderna para Windows y empaquetado autónomo (`VideoStudio-Setup-v1.0.0.exe`) de la suite **VideoStudio Faceless Viral Factory**, impulsada por **Google Antigravity SDK** y un **Router Universal Multi-IA**.

---

## ✨ Características Principales

1. **Instalador Offline Todo-en-Uno (`VideoStudio-Setup-v1.0.0.exe`)**:
   - Interfaz nativa ligera sobre **Windows Edge WebView2** compilada con `PyInstaller` e **Inno Setup 6**.
   - Incluye binarios completos de **`ffmpeg.exe` y `ffprobe.exe`** (con soporte `h264_nvenc` y `libass`) dentro del propio instalador.
   - Aísla todos tus canales, sesiones de redes, historial de 30 días y claves cifradas con **Windows DPAPI** en `%APPDATA%\VideoStudio` para que ninguna actualización borre tu configuración.
2. **SDK Oficial `google-antigravity` + Router Universal Multi-IA**:
   - Conecta **OpenRouter, OmniRouter, Google Gemini, Anthropic (Claude), OpenAI (GPT), Groq e IA Local (Ollama / LM Studio)**.
   - Escáner en vivo que clasifica modelos **GRATIS (`$0`)** frente a **PAGOS**, detecta soporte de **VISIÓN** y ofrece **3 perfiles en 1 clic** (*100% Gratis*, *Equilibrado Recomendado*, *Máxima Potencia Pro*) o selección individual para cada uno de los **9 subagentes**.
3. **Wizard Post-Instalación de 4 Pasos (Reemplazo Visual del `Grill-Me`)**:
   - Diagnóstico automático de GPU/FFmpeg/Stock, conexión de IAs, creador de canal con **botón `▶ Oír` en vivo para las 8 voces Edge-TTS**, simulador móvil 9:16 de subtítulos (`Hormozi` / `Hybrid`), login social en 1 clic y programación diaria en Windows.
4. **Barra Superior de Versión + Auto-Actualizador de 1 Clic desde GitHub**:
   - Muestra la versión actual (`v1.0.0`), tolera limpiamente repositorios aún sin publicar (`Repo Git pendiente`), y al detectar un nuevo Release en GitHub descarga el `.exe`, verifica su firma `MZ` + `SHA-256` y actualiza en 1 clic.

---

## 🚀 Comandos Rápidos (Desarrollo y Empaquetado)

```powershell
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar suite de pruebas completa
python tests\test_suite.py

# Abrir la aplicación en modo escritorio
python src\main.py

# Compilar el instalador completo Offline Todo-en-Uno (.exe + SHA256SUMS.txt)
python installer\build_installer.py
```

---

## 🔗 Repositorio Hermano (Motor CLI)
* **CLI Engine:** [`VideoStudio-Facelessviral-CLI`](https://github.com/sephirods/VideoStudio-Facelessviral-CLI)
* **Guía Técnica y Publicación de Releases:** [`docs/ARCHITECTURE_AND_RELEASES.md`](docs/ARCHITECTURE_AND_RELEASES.md)
