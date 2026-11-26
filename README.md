# GigaControl Center

Aplicación gráfica nativa para **Linux (Pop!_OS / Ubuntu)** inspirada en **Gigabyte Control Center (Windows)** para laptops **Gigabyte G5 / G6 / G7** (plataforma Clevo ODM), construida sobre el daemon y protocolo EC de [`smairio/gigactl`](https://github.com/smairio/gigactl).

![Licencia](https://img.shields.io/badge/license-MIT-orange) ![Plataforma](https://img.shields.io/badge/Linux-Pop!__OS%20%7C%20Ubuntu%2024.04-blue) ![Interfaz](https://img.shields.io/badge/GUI-GTK4%20%2B%20Libadwaita-brightgreen)

## Características principales

- **Panel General**:
  - Escenarios rápidos en 1 clic (`Silencioso`, `Equilibrado`, `Gaming`, `Turbo Máx`, `Auto BIOS`).
  - Medidores circulares Cairo en tiempo real con temperatura CPU/GPU, RPM y `%` de ventiladores, uso de procesador, VRAM, consumo GPU (`nvidia-smi`), RAM y accesos directos.
- **Teclado RGB, Brillo y Teclas Rápidas**:
  - Vista previa interactiva del teclado RGB de zona única.
  - Encendido/apagado, 12 colores rápidos, selector RGB completo, entrada hexadecimal (`#FF6B00`) y slider de brillo (`0–100 %`).
  - Control continuo de brillo de pantalla sin contraseña vía `systemd-logind`.
  - **Soporte de teclas de acceso rápido para iluminación**: atajos globales automáticos en COSMIC (`Super + Alt + NumPad`) + teclas multimedia estándar (`XF86KbdLightOnOff`, `XF86KbdBrightnessUp`, `XF86KbdBrightnessDown`, `XF86Launch1`) y notificaciones OSD.
  - **Driver WMI DKMS opcional** (`kernel/gigactl-hotkeys/`) para habilitar las teclas físicas `Fn + /`, `Fn + *`, `Fn + -`, `Fn + +` del portátil sin competir con `gigactld`.
- **Control de Ventiladores**:
  - Perfiles `Silencioso`, `Equilibrado`, `Rendimiento`, `Máximo (100%)` y `Firmware Auto`.
  - Control manual directo independiente o vinculado para CPU (`Fan 1`) y GPU (`Fan 2`) con piso de seguridad (`>= 30 %` cuando CPU `>= 85 °C`).
  - Editor gráfico interactivo de curva térmica personalizada de 5 nodos arrastrables (`°C → %`), vinculada o separada.
- **Rendimiento y Gráficos**:
  - Cambio de perfil de energía de Pop!_OS (`battery`, `balanced`, `performance` vía `system76-power` / `UPower.PowerProfiles`).
  - Consulta y cambio de modo de GPU (`nvidia`, `hybrid`, `integrated`, `compute`).
  - Telemetría detallada de CPU, frecuencias, `intel_pstate`, GPU NVIDIA y temperatura NVMe.
- **Optimización de Energía**:
  - Presets instantáneos en 1 clic sin contraseña (`Máximo Ahorro`, `Oficina / Estudio`, `Máxima Potencia`).
  - Ajuste fino de `intel_pstate` (`Intel Turbo Boost`, límite máximo `%` de CPU, preferencia `EPP` y `HWP Dynamic Boost`) mediante `pkexec`.

## Requisitos

1. Tener instalado y activo [`smairio/gigactl`](https://github.com/smairio/gigactl) (`gigactld` en D-Bus).
2. Paquetes del sistema (Ubuntu 24.04 / Pop!_OS 24.04):
   ```bash
   sudo apt install gcc make python3 python3-gi python3-gi-cairo python3-psutil \
     gir1.2-gtk-4.0 gir1.2-adw-1 desktop-file-utils
   ```
3. *(Opcional, solo si quieres activar las teclas físicas `Fn` del chasis)*:
   ```bash
   sudo apt install dkms linux-headers-$(uname -r)
   ```

## Compilación e instalación

```bash
make
make install-user
```

Esto compila el lanzador ELF nativo (`build/gigabyte-control-center`) y empaqueta los módulos compilados en `.pyz`, instalando:
- Ejecutable: `~/.local/bin/gigabyte-control-center`
- Datos, helpers y driver opcional: `~/.local/share/gigabyte-control-center/`
- Icono y acceso directo del sistema: `~/.local/share/applications/io.github.gigactl.ControlCenter.desktop`
- Atajos globales de COSMIC (si usas COSMIC): `~/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom`

## Teclas de acceso rápido de iluminación

| Acción | Atajo físico (con driver `Fn`) | Atajo global COSMIC (inmediato) | Comando CLI |
|---|---|---|---|
| Encender / Apagar luz | `Fn + /` (`XF86KbdLightOnOff`) | `Super + Alt + /` | `gigabyte-control-center --kbd-toggle` |
| Subir brillo (+20%) | `Fn + +` (`XF86KbdBrightnessUp`) | `Super + Alt + +` | `gigabyte-control-center --kbd-up` |
| Bajar brillo (-20%) | `Fn + -` (`XF86KbdBrightnessDown`) | `Super + Alt + -` | `gigabyte-control-center --kbd-down` |
| Siguiente color RGB | `Fn + *` (`XF86Launch1`) | `Super + Alt + *` | `gigabyte-control-center --kbd-color-next` |

Para activar también las teclas físicas `Fn` de la laptop, abre la pestaña **Teclado RGB y Brillo** y pulsa **Instalar driver Fn (DKMS)** (o ejecuta `sudo ./scripts/install-hotkeys-driver.sh`).

## Uso por línea de comandos

```bash
gigabyte-control-center                  # Abre la interfaz gráfica
gigabyte-control-center --status         # Muestra estado de hardware y hotkeys
gigabyte-control-center --kbd-toggle     # Alterna luz del teclado
gigabyte-control-center --kbd-up         # Sube brillo +20%
gigabyte-control-center --kbd-down       # Baja brillo -20%
gigabyte-control-center --kbd-color-next # Cicla colores RGB
gigabyte-control-center --kbd-color FF6B00
gigabyte-control-center --kbd-brightness 80
gigabyte-control-center --install-hotkeys
```

## Pruebas

```bash
make test
gigabyte-control-center --smoke-test
```

## Subir a GitHub

El repositorio ya incluye `.gitignore`, `LICENSE`, `CONTRIBUTING.md`, plantilla de issues y GitHub Actions CI:

```bash
git remote add origin https://github.com/<tu-usuario>/<tu-repo>.git
git push -u origin main
```

## Créditos y licencia

- Basado en la ingeniería inversa del protocolo EC de [`smairio/gigactl`](https://github.com/smairio/gigactl).
- Código de la aplicación bajo licencia **MIT** ([LICENSE](LICENSE)). El módulo opcional del kernel bajo `kernel/gigactl-hotkeys/` usa **GPL-2.0-or-later**.
