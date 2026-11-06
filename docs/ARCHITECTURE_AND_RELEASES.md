# Arquitectura y Guía de Actualizaciones de 1 Clic (`VideoStudio Pro Windows`)

## 1. Resumen de Componentes
- **`src/ai/universal_bridge.py`**: Integra el SDK oficial `google-antigravity` (`LocalAgentConfig` + `LocalOpenAIAgentConfig`) junto con un proxy loopback seguro (`127.0.0.1`) que traduce e inyecta credenciales para **OpenRouter, OmniRouter, Anthropic (Claude), OpenAI (GPT), Google Gemini, Groq e IA Local (Ollama / LM Studio)**.
- **`src/ai/model_scanner.py` & `stage_recommender.py`**: Escanea en paralelo tus proveedores conectados, distingue modelos **GRATIS (`$0`)** frente a **PAGOS**, detecta soporte multimodal de **VISIÓN** y recomienda el mejor modelo para cada uno de los 9 subagentes.
- **`src/backend/secret_store.py`**: Cifra todas las API keys en reposo usando **Windows DPAPI (`CryptProtectData`)** dentro de `%APPDATA%\VideoStudio\ai_providers.dpapi.json`.
- **`src/updater/github_updater.py`**: Comprueba `https://api.github.com/repos/<usuario>/<repo>/releases/latest`. Mientras el repositorio no exista o no tenga su primer Release (`HTTP 404`), muestra estado limpio sin errores. Al detectar una versión SemVer mayor, descarga el nuevo `VideoStudio-Setup-vX.Y.Z.exe`, valida su cabecera `MZ` + hash `SHA-256` y lanza la actualización automática conservando intacto `%APPDATA%\VideoStudio`.

---

## 2. Cómo Compilar Manualmente el `instalador.exe` en Windows
```powershell
cd C:\VideoStudio\windows-installer
python installer\build_installer.py
```
El instalador Offline Todo-en-Uno (`ffmpeg.exe` + `ffprobe.exe` + `VideoStudio.exe` + motor de 9 subagentes) quedará listo en:
- `C:\VideoStudio\windows-installer\Output\VideoStudio-Setup-v1.0.0.exe`
- `C:\VideoStudio\windows-installer\Output\SHA256SUMS.txt`

---

## 3. Cómo Publicar el Repo Git y Activar las Actualizaciones en 1 Clic
1. Crea tu repositorio en GitHub (por ejemplo `sephirods/VideoStudio-Windows-Installer`).
2. Conecta este directorio y sube el código (nota: `Output/*.exe`, `dist/` y `build/` están ignorados en `.gitignore` para no ensuciar Git con binarios pesados):
   ```powershell
   cd C:\VideoStudio\windows-installer
   git remote add origin https://github.com/sephirods/VideoStudio-Windows-Installer.git
   git add .
   git commit -m "feat: release VideoStudio Pro Windows Offline All-in-One v1.0.0"
   git push -u origin main
   ```
3. Para lanzar una nueva versión (ej. `v1.1.0`) y que a todos los usuarios les aparezca el botón verde **`🚀 Actualizar a v1.1.0 en 1 Clic`** en la barra superior:
   - **Opción Automática (GitHub Actions ya configurado):**
     ```powershell
     git tag v1.1.0
     git push origin v1.1.0
     ```
     El workflow `.github/workflows/release-windows.yml` compilará automáticamente `VideoStudio-Setup-v1.1.0.exe` + `SHA256SUMS.txt` y creará el Release en GitHub.
   - **Opción Manual:** Sube `Output/VideoStudio-Setup-v1.1.0.exe` y `Output/SHA256SUMS.txt` a un nuevo Release `v1.1.0` en GitHub Releases (permite archivos de hasta 2 GB).
