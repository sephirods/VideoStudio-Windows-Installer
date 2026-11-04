# 🪟 VideoStudio - Windows Installer Edition

Instalador de escritorio y distribución autónoma para Windows de la suite **VideoStudio Faceless Viral Factory**.

---

## 🎯 Propósito
Este repositorio contiene el instalador de 1 clic, dependencias empaquetadas (FFmpeg, Python runtime, entorno portable) y el asistente gráfico para usuarios de Windows, permitiendo instalar y ejecutar la factoría sin necesidad de configurar terminales complejas.

---

## 🗺️ Estructura del Proyecto

* **`installer/`**: Scripts de empaquetado (Inno Setup / NSIS).
* **`src/`**: Lanzador visual y asistente de configuración para Windows.
* **`assets/`**: Iconos (`.ico`), banners y recursos gráficos del instalador.
* **`docs/`**: Documentación técnica del empaquetado y distribución.

---

## 🔗 Repositorio Hermano (Motor CLI)
Este instalador distribuye y conecta con el motor maestro:
* **CLI Engine:** [`VideoStudio-Facelessviral-CLI`](https://github.com/sephirods/VideoStudio-Facelessviral-CLI)
