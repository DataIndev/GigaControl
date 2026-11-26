# Contribuir a GigaControl Center

¡Gracias por tu interés en mejorar **GigaControl Center**!

## Requisitos de desarrollo

- Ubuntu 24.04 LTS / Pop!_OS 24.04 LTS (o derivado con GTK 4 + Libadwaita 1.5+).
- `gcc`, `make`, `python3`, `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-psutil`, `desktop-file-utils`.
- Para compilar el módulo opcional de kernel `gigactl_hotkeys`: `linux-headers-$(uname -r)` y `dkms`.
- Backend `gigactl` (`gigactld`) instalado desde [smairio/gigactl](https://github.com/smairio/gigactl).

## Flujo de trabajo

1. Compila y ejecuta los tests locales:
   ```bash
   make
   make test
   ```
2. Verifica el lanzador de escritorio:
   ```bash
   desktop-file-validate ~/.local/share/applications/io.github.gigactl.ControlCenter.desktop
   ```
3. Prueba la interfaz gráfica sin dejar cambios permanentes:
   ```bash
   ./build/gigabyte-control-center --smoke-test
   ```

## Reglas de seguridad de hardware

- **Nunca escribas directamente al EC** desde la GUI cuando `gigactld` está activo: toda operación de ventiladores o LED debe pasar por D-Bus a `io.github.smairio.gigactl`.
- Respeta siempre el piso térmico de seguridad (`>= 30 %` a `>= 85 °C`) y mantén visible el botón de escape a **Firmware Auto**.
- El módulo `kernel/gigactl-hotkeys/` solo traduce eventos WMI a `input_dev`; nunca escribe registros LED del EC.
